"""Gemini API service for PDF extraction."""

import base64
import json
from pathlib import Path
from typing import Any, Optional

from google import genai
from google.genai import types

from .config_loader import (
    CustomerConfig,
    load_customer_config,
    get_max_signal_prompt_entries,
)
from .prompt_builder import (
    PROMPT_VERSION,
    PromptInput,
    build_assembly_prompt,
    build_minimal_prompt,
    build_text_signals_section,
)
from .types import ExtractionOptions, OrderDetails
from .utils import get_api_key


# JSON schema for Gemini structured output
ORDER_DETAILS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "partNumber": {"type": "string"},
                    "holes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "count": {"type": "number"},
                                "type": {"type": "string"},
                                "diameter": {"type": "string"},
                                "threadSize": {"type": "string"},
                                "tolerance": {"type": "string"},
                                "depth": {"type": "string"},
                                "location": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                    "toleratedLengths": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dimension": {"type": "string"},
                                "notes": {"type": "string"},
                                "toleranceType": {"type": "string"},
                                "upperTolerance": {"type": "string"},
                                "lowerTolerance": {"type": "string"},
                            },
                        },
                    },
                    "surfaceTreatment": {"type": "string"},
                    "material": {"type": "string"},
                    "notes": {"type": "string"},
                    "bomPartNumbers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Part numbers from BOM table, empty array if no BOM",
                    },
                },
            },
        },
        "detectedSignals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "rawValue": {"type": "string"},
                    "page": {"type": "number"},
                    "source": {"type": "string"},
                    "context": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        },
    },
    "required": ["items"],
}


def read_pdf_as_base64(pdf_path: Path) -> str:
    """Read a PDF file and return as base64 string."""
    with open(pdf_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def normalize_surface_treatment(value: Any) -> Optional[str]:
    """Normalize surface treatment value."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    trimmed = value.strip()
    return trimmed if trimmed else None


def apply_customer_surface_treatment_fixes(
    customer_id: str,
    extracted: Optional[str],
    is_assembly: bool,
) -> Optional[str]:
    """Apply customer-specific surface treatment fixes."""
    if not extracted:
        return extracted

    st = extracted.strip()

    # Rademaker-specific fixes
    if customer_id.lower() == "rademaker":
        if is_assembly and (
            st.lower() in ["see remark(s) on drawing", "see remarks on drawing"]
        ):
            return "Finish (see remarks on drawing)"
        if st.upper() in ["CR_FINISH_2B", "CR_FINISH_2D", "BA_FINISH"]:
            return "None"

    return extracted


def build_tolerated_length_instructions(config: CustomerConfig) -> str:
    """Build tolerated length instructions from config."""
    if not config.signals or not config.signals.tolerated_lengths:
        return "          - Note: No special length patterns defined."

    lines = []
    for i, signal in enumerate(config.signals.tolerated_lengths):
        pattern = signal.pattern or "unknown pattern"
        desc = signal.description or "treat as critical tolerance, add to toleratedLengths."
        lines.append(f'          - Pattern {i + 1}: "{pattern}" -> {desc}')

    return "\n".join(lines)


def build_hole_instructions(config: CustomerConfig) -> str:
    """Build hole instructions from config."""
    if not config.signals or not config.signals.holes:
        return "          - Note: No special hole recipes defined."

    lines = []
    for i, hole in enumerate(config.signals.holes):
        pattern = hole.pattern or "unknown hole pattern"
        h_type = hole.capture.get("type", "normal") if hole.capture else "normal"
        diameter = f", diameter={hole.capture['diameter']}" if hole.capture and hole.capture.get("diameter") else ""
        thread = f", threadSize={hole.capture['threadSize']}" if hole.capture and hole.capture.get("threadSize") else ""
        tolerance = f", tolerance='{hole.capture['tolerance']}'" if hole.capture and hole.capture.get("tolerance") else ""
        lines.append(
            f'          - Recipe {i + 1}: When you see "{pattern}", '
            f"set type='{h_type}'{diameter}{thread}{tolerance}."
        )

    return "\n".join(lines)


def build_surface_treatment_instructions(config: CustomerConfig, customer_name: str) -> str:
    """Build surface treatment instructions from config."""
    if config.surface_treatments and config.surface_treatments.enabled:
        options_text = "\n            ".join(
            f'* "{opt.display_name}"'
            + (f" (keywords: {', '.join(opt.keywords)})" if opt.keywords else "")
            for opt in config.surface_treatments.options
        )
        return f"\n            VALID OPTIONS for {customer_name}:\n            {options_text}"

    return 'Look for surface treatment specifications. If not found, use "None".'


def build_material_instructions(config: CustomerConfig) -> str:
    """Build material instructions from config."""
    material_rules = list(config.material_patterns)

    if config.prompt_additions and config.prompt_additions.material:
        material_rules.extend(config.prompt_additions.material)

    material_rules = [r.strip() for r in material_rules if isinstance(r, str) and r.strip()]

    if not material_rules:
        return "          - Note: No special material patterns defined."

    return "\n".join(f"          - {rule}" for rule in material_rules)


async def extract_order_details_from_pdf(
    pdf_base64: str,
    options: Optional[ExtractionOptions] = None,
) -> OrderDetails:
    """
    Extract order details from a PDF using Gemini API.

    Args:
        pdf_base64: Base64-encoded PDF content
        options: Extraction options

    Returns:
        OrderDetails with extracted data
    """
    if options is None:
        options = ExtractionOptions()

    customer_id = options.customer_id
    text_signals = options.text_signals
    pdf_filename = options.pdf_filename
    model_name = options.model
    is_assembly = options.is_assembly

    # Load customer config
    config = load_customer_config(customer_id)
    customer_name = config.customer_name or customer_id.upper()

    # Build instruction strings
    max_signal_entries = get_max_signal_prompt_entries(config)
    text_signals_section, _ = build_text_signals_section(text_signals, max_signal_entries)

    tolerated_length_instructions = build_tolerated_length_instructions(config)
    hole_instructions = build_hole_instructions(config)
    surface_treatment_instructions = build_surface_treatment_instructions(config, customer_name)
    material_instructions = build_material_instructions(config)

    # Build prompt additions dict
    prompt_additions = None
    if config.prompt_additions:
        prompt_additions = {
            "holes": config.prompt_additions.holes,
            "tolerated_lengths": config.prompt_additions.tolerated_lengths,
            "surface_treatment": config.prompt_additions.surface_treatment,
        }

    # Build the prompt
    if is_assembly:
        prompt = build_assembly_prompt(customer_name, surface_treatment_instructions)
    else:
        prompt_input = PromptInput(
            customer_name=customer_name,
            images_count=1,
            tolerated_length_instructions=tolerated_length_instructions,
            hole_instructions=hole_instructions,
            surface_treatment_instructions=surface_treatment_instructions,
            material_instructions=material_instructions,
            text_signals_section=text_signals_section,
            prompt_additions=prompt_additions,
        )
        prompt = build_minimal_prompt(prompt_input)

    # Configure Gemini client (new google-genai API)
    api_key = get_api_key()
    client = genai.Client(api_key=api_key)

    # Create PDF part
    pdf_part = types.Part.from_bytes(
        data=base64.b64decode(pdf_base64),
        mime_type="application/pdf",
    )

    # Generate content with JSON response
    response = await client.aio.models.generate_content(
        model=model_name,
        contents=[prompt, pdf_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ORDER_DETAILS_SCHEMA,
            temperature=0.0,
            top_p=0.1,
            max_output_tokens=4096,
        ),
    )

    json_text = response.text
    if not json_text:
        raise ValueError("Empty response from Gemini")

    # Parse response
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response from Gemini: {e}") from e

    # Assign part number from filename
    part_number = pdf_filename or "unknown_part_1"
    if "items" in data:
        for item in data["items"]:
            item["partNumber"] = part_number

    # Post-process surface treatment
    if "items" in data:
        for item in data["items"]:
            normalized = normalize_surface_treatment(item.get("surfaceTreatment"))
            fixed = apply_customer_surface_treatment_fixes(customer_id, normalized, is_assembly)
            if fixed != normalized:
                item["surfaceTreatment"] = fixed or "None"

    # Create OrderDetails model
    order_details = OrderDetails(**data)

    # Attach text signals for traceability
    if text_signals:
        if order_details.detected_signals:
            order_details.detected_signals.extend(text_signals)
        else:
            order_details.detected_signals = text_signals

    return order_details


# Synchronous wrapper for simpler usage
def extract_order_details_from_pdf_sync(
    pdf_base64: str,
    options: Optional[ExtractionOptions] = None,
) -> OrderDetails:
    """Synchronous version of extract_order_details_from_pdf."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # Already in async context - create new loop in thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, extract_order_details_from_pdf(pdf_base64, options))
            return future.result()
    else:
        return asyncio.run(extract_order_details_from_pdf(pdf_base64, options))
