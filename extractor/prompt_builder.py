"""Prompt builder for Gemini API extraction.

v2.2-cot: Lean chain-of-thought, few-shot examples, anti-hallucination guardrails.
Config-driven: specific keywords/patterns come from YAML, not hardcoded here.
"""

from dataclasses import dataclass
from typing import Optional

from .types import TextSignal

PROMPT_VERSION = "v2.2-cot"


@dataclass
class PromptInput:
    """Input for building the extraction prompt."""
    customer_name: str
    images_count: int
    tolerated_length_instructions: str
    hole_instructions: str
    surface_treatment_instructions: str
    material_instructions: str
    text_signals_section: Optional[str] = None
    prompt_additions: Optional[dict[str, list[str]]] = None


def build_text_signals_section(
    signals: list[TextSignal],
    max_entries: int = 5,
) -> tuple[str, int]:
    """Build the text signals section for the prompt."""
    if not signals:
        return (
            "### OCR Cues (REFERENCE ONLY)\n"
            "No OCR matches. Extract ONLY from what you SEE in the PDF images.",
            0,
        )

    limited_signals = signals[:max_entries]
    truncated_count = len(signals) - len(limited_signals)

    lines = []
    for i, s in enumerate(limited_signals):
        ctx = (s.context or "").replace("\n", " ").strip()
        short_ctx = f"{ctx[:77]}..." if len(ctx) > 80 else ctx
        ctx_part = f' | context: "{short_ctx}"' if short_ctx else ""
        lines.append(
            f"  {i + 1}. [{s.category.upper()}] {s.raw_value} "
            f"(page {s.page}, {s.source}){ctx_part}"
        )

    extra_line = f"\n  ...and {truncated_count} more cue(s)." if truncated_count > 0 else ""

    section = f"""### OCR Cues (REFERENCE ONLY — verify in PDF)
{chr(10).join(lines)}{extra_line}"""

    return section, truncated_count


def _build_few_shot_section() -> str:
    """Build few-shot examples for the prompt."""
    return """
**EXAMPLES:**

Example 1 — Part with coating and tolerances:
BOM: Material="S235JR 3mm", row text includes "Poedercoaten RAL7035"
Drawing: 2x Ø10 H7, 1x M6, dimension 150 ±0.2
→ Output:
{"material": "S235JR 3mm", "surfaceTreatment": "Poedercoaten RAL7035",
 "holes": [{"type": "normal", "diameter": "10", "tolerance": "H7", "count": 2},
           {"type": "tapped", "threadSize": "M6", "count": 1}],
 "toleratedLengths": [{"dimension": "150", "upperTolerance": "0.2", "lowerTolerance": "-0.2"}],
 "bomPartNumbers": []}

Example 2 — Simple part, no coating, no tolerances:
BOM: Material="AISI 304 DIN 1.4301 2mm", no coating keywords found
Drawing: Ø30 (no tolerance), plain dimensions only
→ Output:
{"material": "AISI 304 DIN 1.4301 2mm", "surfaceTreatment": "None",
 "holes": [], "toleratedLengths": [], "bomPartNumbers": []}
"""


def build_assembly_prompt(
    customer_name: str,
    surface_treatment_instructions: str,
) -> str:
    """Build prompt for assembly drawing (BOM-only extraction)."""
    return f"""Extract manufacturing data from technical drawing PDF.

This is a MAIN ASSEMBLY: extract ONLY from BOM + title block.
Return: material, surfaceTreatment, bomPartNumbers.
DO NOT extract holes or toleranced dimensions.

Customer: {customer_name}
Surface treatments:{surface_treatment_instructions}

Return valid JSON per schema.
[prompt_version: {PROMPT_VERSION}]"""


def build_minimal_prompt(p: PromptInput) -> str:
    """Build the extraction prompt with chain-of-thought steps."""
    signals = f"\n{p.text_signals_section}\n" if p.text_signals_section else ""

    # Build customer-specific additions for each section
    hole_additions = ""
    if p.prompt_additions and p.prompt_additions.get("holes"):
        hole_additions = "\n  Customer-specific:\n" + "\n".join(
            f"    - {rule}" for rule in p.prompt_additions["holes"]
        )

    surface_additions = ""
    if p.prompt_additions and p.prompt_additions.get("surface_treatment"):
        surface_additions = "\n  Customer-specific:\n" + "\n".join(
            f"    - {rule}" for rule in p.prompt_additions["surface_treatment"]
        )

    few_shot = _build_few_shot_section()

    return f"""Extract manufacturing data from this technical drawing PDF.
Return exactly 1 item ({p.images_count} page(s), same part). Use null for missing data.

**FOLLOW THESE STEPS IN ORDER:**

**Step 1: SCAN THE BOM TABLE** (bottom-right of drawing)
Read the entire BOM table. This is where you find surface treatment, material, and sub-component part numbers.

**Step 2: SURFACE TREATMENT**
Search BOM rows, title block, and notes for coating/finish keywords (see valid options below).
If no match is found anywhere, return "None". Do NOT infer coating from material type.{surface_additions}

**Step 3: MATERIAL**
Read the COMPLETE text from the material field — include thickness if present (e.g. "RVS 2 mm", NOT just "RVS").
Ignore generic shape types: "Sheet", "Plaat", "Tube", "Buis" — these are NOT materials.

**Step 4: HOLES** (from main drawing views only)
- Normal: Ø20 or Ø20 H9 → type=normal, diameter=20, tolerance=H9
- Tapped: M6 or 4x M6 → type=tapped, threadSize=M6, count=4
- Reamed: pre-drill + final → type=reamed, notes="Pre-drill Ø19.5"
- Same hole at multiple locations → SEPARATE entries per location (don't combine unless explicitly labeled "2x" etc.){hole_additions}

**Step 5: TOLERANCED DIMENSIONS** (from main drawing views only)
Only dimensions with explicit ± or +/- or +X/0 symbols AND dimension lines/arrows.
Diameter tolerances (e.g. Ø40 H7) belong in HOLES, not here.
Ignore: plain numbers, general tolerance tables, BOM values.

**Step 6: BOM PART NUMBERS**
If drawing has a BOM with sub-components, extract all part numbers (not quantities/descriptions).
Ignore the main part number from the title block. Return [] if no BOM.
{few_shot}
**RULES — do NOT violate:**
- Extract ONLY what is VISIBLE in the PDF images.
- If you cannot clearly read a value, use null. Do NOT guess.
- If a hole count is ambiguous, report what you see, not what you infer.
- If surface treatment is not explicitly stated, return "None".

**Customer: {p.customer_name}**

Tolerated lengths patterns:
{p.tolerated_length_instructions}

Hole patterns:
{p.hole_instructions}

Surface treatments:
{p.surface_treatment_instructions}

Material patterns:
{p.material_instructions}
{signals}
Return valid JSON per schema.
[prompt_version: {PROMPT_VERSION}]
"""
