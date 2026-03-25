"""Ollama service for local model-based extraction from PDF text or vision."""

import base64
import json
import re
from io import BytesIO
from typing import Any, Optional
from urllib import error, request

from pypdf import PdfReader

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional runtime dependency in text mode
    fitz = None

from .config_loader import load_customer_config
from .types import ExtractionOptions, OrderDetails


def _extract_text_from_pdf_base64(pdf_base64: str) -> str:
    """Extract plain text from PDF bytes for local-model processing."""
    pdf_bytes = base64.b64decode(pdf_base64)
    reader = PdfReader(BytesIO(pdf_bytes))
    pages: list[str] = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(page_text.strip())

    return "\n\n".join(pages)


def _extract_images_from_pdf_base64(pdf_base64: str, max_pages: int = 3) -> list[str]:
    """Render first PDF pages to PNG base64 for Ollama vision models."""
    if fitz is None:
        raise RuntimeError(
            "Vision mode requires 'pymupdf'. Install with: pip install pymupdf"
        )

    pdf_bytes = base64.b64decode(pdf_base64)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images: list[str] = []

    page_count = min(len(doc), max_pages)
    for idx in range(page_count):
        page = doc.load_page(idx)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        png_bytes = pix.tobytes("png")
        images.append(base64.b64encode(png_bytes).decode("utf-8"))

    return images


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Parse JSON object from model response text, allowing fenced code blocks."""
    text = raw.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ollama response is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Ollama response JSON must be an object")

    return parsed


def _build_ollama_prompt(
    customer_id: str,
    model_hint: str,
    source_text: str,
    mode: str,
) -> str:
    """Build a strict JSON extraction prompt for Ollama."""
    config = load_customer_config(customer_id)
    customer_name = config.customer_name or customer_id.upper()

    surface_options = ""
    if config.surface_treatments and config.surface_treatments.options:
        options = [opt.display_name for opt in config.surface_treatments.options]
        surface_options = "Allowed surface treatment values: " + ", ".join(options)

    source_label = "technical drawing text" if mode == "text" else "technical drawing images"

    return f"""You are extracting manufacturing data from {source_label}.

Target customer: {customer_name}
Model hint: {model_hint}

Rules:
- Return JSON only (no markdown, no comments).
- Output shape must be:
  {{
    "items": [
      {{
        "partNumber": string,
        "surfaceTreatment": string,
        "material": string,
        "holes": [
          {{
            "count": number,
            "type": string,
            "diameter": string,
            "threadSize": string,
            "tolerance": string,
            "notes": string
          }}
        ],
        "toleratedLengths": [
          {{
            "dimension": string,
            "upperTolerance": string,
            "lowerTolerance": string,
            "toleranceType": string,
            "notes": string
          }}
        ],
        "bomPartNumbers": [string],
        "notes": string
      }}
    ]
  }}
- If unknown, use null or empty arrays.
- Do not invent part numbers.
- Only include explicit toleranced dimensions in toleratedLengths.
- Diameter tolerances belong in holes, not toleratedLengths.
- If no BOM list is present, use bomPartNumbers: [].
- {surface_options if surface_options else 'If no surface treatment is found, use "None".'}

Source mode: {mode}

Extract from this source material:
{source_text}
"""


def _ollama_chat(
    base_url: str,
    model: str,
    prompt: str,
    images: Optional[list[str]] = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Call Ollama chat API and return parsed JSON response object."""
    url = f"{base_url.rstrip('/')}/api/chat"
    user_message: dict[str, Any] = {"role": "user", "content": prompt}
    if images:
        user_message["images"] = images

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return strictly valid JSON for the requested schema.",
            },
            user_message,
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }

    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {base_url}. Is 'ollama serve' running? ({exc})"
        ) from exc

    response_obj = json.loads(raw)
    message = response_obj.get("message", {})
    content = message.get("content")
    if not content:
        raise ValueError("Ollama response did not include message.content")

    return _extract_json_object(content)


def _normalize_surface_treatment(value: Any) -> Optional[str]:
    """Strip and normalise a surface treatment value."""
    if value is None:
        return None
    trimmed = str(value).strip()
    return trimmed or None


def _apply_customer_surface_treatment_fixes(
    customer_id: str,
    extracted: Optional[str],
    is_assembly: bool,
) -> Optional[str]:
    """Apply customer-specific post-processing to surface treatment values."""
    if not extracted:
        return extracted

    st = extracted.strip()

    if customer_id.lower() == "rademaker":
        if is_assembly and st.lower() in [
            "see remark(s) on drawing",
            "see remarks on drawing",
        ]:
            return "Finish (see remarks on drawing)"
        if st.upper() in ["CR_FINISH_2B", "CR_FINISH_2D", "BA_FINISH"]:
            return "None"

    return extracted


def _looks_like_vision_model(model_name: str) -> bool:
    """Heuristic to auto-select vision mode for common Ollama vision models."""
    marker_strings = [
        "vision",
        "llava",
        "qwen2.5vl",
        "minicpm-v",
        "moondream",
        "bakllava",
        "phi3v",
    ]
    name = model_name.lower()
    return any(marker in name for marker in marker_strings)


async def extract_order_details_from_pdf_ollama(
    pdf_base64: str,
    options: Optional[ExtractionOptions] = None,
) -> OrderDetails:
    """Extract order details via a local Ollama model (text or vision mode)."""
    if options is None:
        options = ExtractionOptions(provider="ollama")

    mode = options.ollama_mode
    if mode == "auto":
        mode = "vision" if _looks_like_vision_model(options.model) else "text"

    images: Optional[list[str]] = None
    if mode == "vision":
        images = _extract_images_from_pdf_base64(pdf_base64, max_pages=3)
        if not images:
            raise ValueError("Could not render PDF pages for Ollama vision mode.")
        source_text = (
            "Use provided page images for extraction. "
            "Do not invent values not visible in the drawing."
        )
    else:
        pdf_text = _extract_text_from_pdf_base64(pdf_base64)
        if not pdf_text.strip():
            raise ValueError(
                "No readable PDF text found for Ollama text mode. "
                "Try --ollama-mode vision with a vision-capable model."
            )
        source_text = pdf_text

    prompt = _build_ollama_prompt(
        customer_id=options.customer_id,
        model_hint=options.model,
        source_text=source_text,
        mode=mode,
    )

    data = _ollama_chat(
        base_url=options.ollama_base_url,
        model=options.model,
        prompt=prompt,
        images=images,
    )

    data.setdefault("items", [])

    part_number = options.pdf_filename or "unknown"
    for item in data.get("items", []):
        item["partNumber"] = part_number

    for item in data.get("items", []):
        normalized = _normalize_surface_treatment(item.get("surfaceTreatment"))
        fixed = _apply_customer_surface_treatment_fixes(
            options.customer_id,
            normalized,
            options.is_assembly,
        )
        if fixed != normalized:
            item["surfaceTreatment"] = fixed or "None"

    return OrderDetails(**data)
