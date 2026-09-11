"""Gemini API service for PDF extraction."""

import base64
import json
import re
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from .config_loader import (
    CustomerConfig,
    get_max_signal_prompt_entries,
    load_customer_config,
)
from .prompt_builder import (
    PromptInput,
    build_assembly_prompt,
    build_minimal_prompt,
    build_technical_assembly_prompt,
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
                                "normalizedCode": {"type": "string"},
                                "type": {"type": "string"},
                                "operation": {"type": "string"},
                                "diameter": {"type": "string"},
                                "threadSize": {"type": "string"},
                                "tolerance": {"type": "string"},
                                "upperTolerance": {"type": "string"},
                                "lowerTolerance": {"type": "string"},
                                "cuttingSize": {"type": "string"},
                                "depth": {"type": "string"},
                                "location": {"type": "string"},
                                "evidence": {"type": "string"},
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
                                "relatedFeature": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                        },
                    },
                    "surfaceTreatment": {"type": "string"},
                    "material": {"type": "string"},
                    "revision": {"type": "string"},
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "notes": {"type": "string"},
                    "bomPartNumbers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Part numbers from BOM table, empty array if no BOM",
                    },
                    "bomItems": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "position": {"type": "string"},
                                "partNumber": {"type": "string"},
                                "quantity": {"type": "number"},
                                "description": {"type": "string"},
                                "material": {"type": "string"},
                            },
                        },
                    },
                    "machiningOperations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "normalizedCode": {"type": "string"},
                                "operation": {"type": "string"},
                                "category": {"type": "string"},
                                "targetField": {"type": "string"},
                                "count": {"type": "number"},
                                "diameter": {"type": "string"},
                                "threadSize": {"type": "string"},
                                "tolerance": {"type": "string"},
                                "cuttingSize": {"type": "string"},
                                "relatedFeature": {"type": "string"},
                                "evidence": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                    "technicalAnalysis": {
                        "type": "object",
                        "properties": {
                            "manufacturabilityStatus": {"type": "string"},
                            "conclusion": {"type": "string"},
                            "positiveChecks": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "risks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "severity": {"type": "string"},
                                        "category": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "evidence": {"type": "string"},
                                    },
                                    "required": ["summary"],
                                },
                            },
                            "weldingNotes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "coatingRequirements": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "revisionNotes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "gdtRequirements": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "generalTolerances": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "assemblyDimensions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
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


def normalize_surface_treatment(value: Any) -> str | None:
    """Normalize surface treatment value."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    trimmed = value.strip()
    return trimmed if trimmed else None


def apply_customer_surface_treatment_fixes(
    customer_id: str,
    extracted: str | None,
    is_assembly: bool,
) -> str | None:
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


HOLE_OPERATION_CODES = {
    "DRILL",
    "TAP",
    "REAM",
    "FIT_HOLE",
    "COUNTERSINK",
    "COUNTERBORE",
}

EMPTY_VALUE_MARKERS = {"", "none", "null", "n/a", "na", "-", "geen"}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _has_value(value: Any) -> bool:
    return _clean_text(value).lower() not in EMPTY_VALUE_MARKERS


def _clean_code(value: Any) -> str:
    return _clean_text(value).upper()


_EXPLICIT_OPERATION_PATTERNS = {
    "DRILL": re.compile(
        r"(?i)\b(?:boor(?:gat(?:en)?|werk)?|boren|drill(?:ed|ing|hole|holes)?)\b"
    ),
    "MILL": re.compile(r"(?i)\b(?:frees\w*|frez(?:en|erij)|mill(?:ed|ing)?)\b"),
    "TURN": re.compile(
        r"(?i)\b(?:draai(?:en|werk|bank|bewerking)?|turn(?:ed|ing)?|lathe)\b"
    ),
    "REAM": re.compile(
        r"(?i)\b(?:ruim(?:en|ing|gat(?:en)?)?|ream(?:ed|ing|hole|holes)?)\b"
    ),
    "COUNTERSINK": re.compile(
        r"(?i)(?:\b(?:verzink\w*|verzonk\w*|countersink\w*)\b|\bDIN\s*74\b|[⌵⌄])"
    ),
    "COUNTERBORE": re.compile(
        r"(?i)(?:\b(?:cilinderverzink\w*|counterbor\w*|spotface\w*)\b|⌴)"
    ),
}
_TAP_TERM_PATTERN = re.compile(
    r"(?i)\b(?:tap(?:pen|gat(?:en)?|ped|ping)?|draadgat(?:en)?|threaded\s+hole(?:s)?)\b"
)
_THREAD_SIZE_PATTERN = re.compile(r"(?i)\bM\s*[0-9]+(?:[.,][0-9]+)?\b")
_THREAD_COMPONENT_PATTERN = re.compile(
    r"(?i)\b(?:draadstang|draadeind|threaded\s+(?:rod|stud)|stud|bolt|bout|screw|schroef|DIN\s*976)\b"
)
_HOLE_FIT_PATTERN = re.compile(
    r"(?:Ø|⌀|\bO)\s*[0-9]+(?:[.,][0-9]+)?\s*(?:[A-Z][0-9]{1,2}|[+-])"
)
_SHAFT_FIT_PATTERN = re.compile(
    r"(?:Ø|⌀|\bO)\s*[0-9]+(?:[.,][0-9]+)?\s*[a-z][0-9]{1,2}\b"
)


def _item_manufacturing_context(item: dict[str, Any]) -> str:
    """Collect text used only to reject component/BOM false positives."""

    values = [
        _clean_text(item.get("partNumber")),
        _clean_text(item.get("description")),
        _clean_text(item.get("notes")),
    ]
    for bom_item in item.get("bomItems") or []:
        if not isinstance(bom_item, dict):
            continue
        values.extend(
            _clean_text(bom_item.get(field))
            for field in ("partNumber", "description", "material")
        )
    analysis = item.get("technicalAnalysis")
    if isinstance(analysis, dict):
        values.extend(
            _clean_text(analysis.get(field))
            for field in ("conclusion", "weldingNotes", "coatingRequirements")
        )
    return " ".join(value for value in values if value)


def _is_additional_pdf_feature(code: str, evidence: str, context: str = "") -> bool:
    """Accept only explicit PDF information that adds to STEP geometry."""

    if not code or not _has_value(evidence):
        return False
    if code == "BEND":
        return False
    if code in _EXPLICIT_OPERATION_PATTERNS:
        return bool(_EXPLICIT_OPERATION_PATTERNS[code].search(evidence))
    if code == "TAP":
        if _TAP_TERM_PATTERN.search(evidence):
            return True
        if _THREAD_COMPONENT_PATTERN.search(f"{evidence} {context}"):
            return False
        return bool(_THREAD_SIZE_PATTERN.search(evidence))
    if code == "FIT_HOLE":
        if _SHAFT_FIT_PATTERN.search(evidence):
            return False
        return bool(_HOLE_FIT_PATTERN.search(evidence))
    return True


def _preserve_shaft_tolerance(item: dict[str, Any], evidence: str) -> str:
    """Keep an explicit shaft fit without turning it into a TURN operation."""

    match = _SHAFT_FIT_PATTERN.search(evidence)
    if not match:
        return ""
    callout = match.group(0).strip()
    tolerances = [
        row for row in item.get("toleratedLengths") or [] if isinstance(row, dict)
    ]
    if not any(_clean_text(row.get("evidence")) == callout for row in tolerances):
        tolerances.append(
            {
                "dimension": callout,
                "toleranceType": "shaft_fit",
                "relatedFeature": "shaft",
                "evidence": callout,
            }
        )
    item["toleratedLengths"] = tolerances
    return callout


def filter_additional_pdf_features(data: dict[str, Any]) -> None:
    """Remove geometry-derived features that belong to the STEP engine.

    The filter is intentionally conservative: a structured row survives only
    when its evidence contains an explicit additional manufacturing callout.
    Material, BOM, surface, roughness, welding and tolerance signals remain
    available because those cannot reliably be derived from STEP geometry.
    """

    items = [item for item in data.get("items") or [] if isinstance(item, dict)]
    item_contexts = [_item_manufacturing_context(item) for item in items]

    for item, context in zip(items, item_contexts):
        operations: list[dict[str, Any]] = []
        for operation in item.get("machiningOperations") or []:
            if not isinstance(operation, dict):
                continue
            code = _clean_code(operation.get("normalizedCode"))
            evidence = " ".join(
                value
                for value in (
                    _clean_text(operation.get("evidence")),
                    _clean_text(operation.get("notes")),
                    _clean_text(operation.get("relatedFeature")),
                )
                if value
            )
            if code in {"TURN", "FIT_HOLE", "TOLERANCE"}:
                _preserve_shaft_tolerance(item, evidence)
            if code == "TOLERANCE":
                continue
            if _is_additional_pdf_feature(code, evidence, context):
                operations.append(operation)
        item["machiningOperations"] = operations

        holes: list[dict[str, Any]] = []
        for hole in item.get("holes") or []:
            if not isinstance(hole, dict):
                continue
            code = _clean_code(hole.get("normalizedCode"))
            evidence = " ".join(
                value
                for value in (
                    _clean_text(hole.get("evidence")),
                    _clean_text(hole.get("notes")),
                    _clean_text(hole.get("location")),
                )
                if value
            )
            if code == "FIT_HOLE":
                _preserve_shaft_tolerance(item, evidence)
            if code in HOLE_OPERATION_CODES and _is_additional_pdf_feature(
                code, evidence, context
            ):
                holes.append(hole)
        item["holes"] = holes

    filtered_signals: list[dict[str, Any]] = []
    seen_signals: set[tuple[str, str]] = set()
    for signal in data.get("detectedSignals") or []:
        if not isinstance(signal, dict):
            continue
        code = _clean_code(signal.get("category"))
        raw_value = _clean_text(signal.get("rawValue"))
        signal_context = _clean_text(signal.get("context"))
        matching_contexts = [
            context
            for item, context in zip(items, item_contexts)
            if _signal_context_applies(signal, item, len(items))
        ]
        context = " ".join([signal_context, *matching_contexts])
        if code in {"TURN", "FIT_HOLE", "TOLERANCE"}:
            matching_items = [
                item
                for item in items
                if _signal_context_applies(signal, item, len(items))
            ]
            callout = ""
            for item in matching_items:
                callout = _preserve_shaft_tolerance(item, raw_value) or callout
            if callout:
                key = ("TOLERANCE", callout)
                if key not in seen_signals:
                    converted = dict(signal)
                    converted["category"] = "TOLERANCE"
                    converted["rawValue"] = callout
                    filtered_signals.append(converted)
                    seen_signals.add(key)
                if code != "TOLERANCE":
                    continue
        if _is_additional_pdf_feature(code, raw_value, context):
            key = (code, raw_value)
            if key not in seen_signals:
                filtered_signals.append(signal)
                seen_signals.add(key)
    data["detectedSignals"] = filtered_signals


def _int_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, parsed)


def _merge_text(existing: Any, new: Any) -> str:
    existing_text = _clean_text(existing)
    new_text = _clean_text(new)
    if not existing_text:
        return new_text
    if not new_text or new_text == existing_text:
        return existing_text
    return f"{existing_text} | {new_text}"


def _merge_list_field(
    target: dict[str, Any], incoming: dict[str, Any], field: str
) -> None:
    incoming_values = incoming.get(field)
    if not isinstance(incoming_values, list):
        return

    merged = target.get(field)
    if not isinstance(merged, list):
        merged = []

    for value in incoming_values:
        if value not in merged:
            merged.append(value)

    if merged:
        target[field] = merged


def _merge_dict_field(
    target: dict[str, Any], incoming: dict[str, Any], field: str
) -> None:
    incoming_value = incoming.get(field)
    if not isinstance(incoming_value, dict):
        return

    existing = target.get(field)
    if not isinstance(existing, dict):
        target[field] = incoming_value
        return

    for key, value in incoming_value.items():
        if isinstance(value, list):
            current = existing.get(key)
            if not isinstance(current, list):
                current = []
            for entry in value:
                if entry not in current:
                    current.append(entry)
            if current:
                existing[key] = current
        elif not _has_value(existing.get(key)) and _has_value(value):
            existing[key] = value
        elif key in {"summary", "notes"}:
            existing[key] = _merge_text(existing.get(key), value)


def _merge_item(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for field in ("description", "material", "surfaceTreatment", "revision", "status"):
        if not _has_value(target.get(field)) and _has_value(incoming.get(field)):
            target[field] = incoming.get(field)

    target["notes"] = _merge_text(target.get("notes"), incoming.get("notes")) or None

    if _has_value(incoming.get("quantity")):
        target["quantity"] = max(
            _int_count(target.get("quantity")),
            _int_count(incoming.get("quantity")),
        )

    for field in (
        "holes",
        "toleratedLengths",
        "bomPartNumbers",
        "bomItems",
        "machiningOperations",
    ):
        _merge_list_field(target, incoming, field)

    _merge_dict_field(target, incoming, "technicalAnalysis")


def merge_duplicate_items(data: dict[str, Any]) -> None:
    """Merge fragmented rows that refer to the same PDF part."""

    items = data.get("items")
    if not isinstance(items, list):
        return

    merged: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("partNumber")).lower()
        if not key:
            merged.append(item)
            continue
        if key not in index:
            index[key] = item
            merged.append(item)
            continue
        _merge_item(index[key], item)

    data["items"] = merged


def normalize_machining_operations(data: dict[str, Any]) -> None:
    """Merge duplicate operation rows while preserving repeated locations."""

    for item in data.get("items") or []:
        operations = item.get("machiningOperations")
        if not isinstance(operations, list):
            continue

        merged: list[dict[str, Any]] = []
        index: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            code = _clean_code(operation.get("normalizedCode"))
            if not code and not any(
                _has_value(operation.get(field))
                for field in (
                    "operation",
                    "evidence",
                    "notes",
                    "diameter",
                    "threadSize",
                    "tolerance",
                    "cuttingSize",
                )
            ):
                continue
            if code == "SURFACE_TREATMENT" and not any(
                _has_value(operation.get(field))
                for field in ("evidence", "notes", "surfaceTreatment", "rawValue")
            ):
                continue
            if (
                code == "TAP"
                and _clean_text(operation.get("tolerance")).upper()
                == _clean_text(operation.get("threadSize")).upper()
            ):
                operation.pop("tolerance", None)
            key = (
                code,
                _clean_text(operation.get("operation")).lower(),
                _clean_text(operation.get("diameter")).lower(),
                _clean_text(operation.get("threadSize")).lower(),
                _clean_text(operation.get("tolerance")).lower(),
                _clean_text(operation.get("cuttingSize")).lower(),
            )

            if key not in index:
                operation["normalizedCode"] = code or operation.get("normalizedCode")
                index[key] = operation
                merged.append(operation)
                continue

            existing = index[key]
            existing_count = _int_count(existing.get("count"))
            new_count = _int_count(operation.get("count"))
            same_evidence = _clean_text(existing.get("evidence")) == _clean_text(
                operation.get("evidence")
            )

            if same_evidence and max(existing_count, new_count) > 1:
                existing["count"] = max(existing_count, new_count)
            else:
                existing["count"] = existing_count + new_count
            for field in (
                "diameter",
                "threadSize",
                "tolerance",
                "cuttingSize",
                "relatedFeature",
                "targetField",
            ):
                if not _has_value(existing.get(field)) and _has_value(
                    operation.get(field)
                ):
                    existing[field] = operation.get(field)
            existing["evidence"] = _merge_text(
                existing.get("evidence"), operation.get("evidence")
            )
            existing["notes"] = _merge_text(
                existing.get("notes"), operation.get("notes")
            )

        item["machiningOperations"] = merged


def normalize_holes(data: dict[str, Any]) -> None:
    """Merge duplicate hole rows and clean derived thread/tolerance fields."""

    for item in data.get("items") or []:
        holes = item.get("holes")
        if not isinstance(holes, list):
            continue

        merged: list[dict[str, Any]] = []
        index: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        for hole in holes:
            if not isinstance(hole, dict):
                continue

            code = _clean_code(hole.get("normalizedCode"))
            if not code:
                code = _clean_code(hole.get("type"))
            if code == "TAPPED":
                code = "TAP"
            if code == "REAMED":
                code = "REAM"
            if code == "COUNTERSUNK":
                code = "COUNTERSINK"
            if code:
                hole["normalizedCode"] = code

            evidence = _clean_text(hole.get("evidence"))
            if code == "TAP":
                if not _has_value(hole.get("threadSize")) and evidence:
                    thread_size = _extract_thread_size(evidence)
                    if thread_size:
                        hole["threadSize"] = thread_size
                if (
                    _clean_text(hole.get("tolerance")).upper()
                    == _clean_text(hole.get("threadSize")).upper()
                ):
                    hole.pop("tolerance", None)
            if code in HOLE_OPERATION_CODES and evidence:
                if not _has_value(hole.get("diameter")):
                    diameter = _extract_diameter(evidence)
                    if diameter:
                        hole["diameter"] = diameter
                if not _has_value(hole.get("tolerance")):
                    tolerance = _extract_hole_tolerance(evidence)
                    if tolerance:
                        hole["tolerance"] = tolerance
                if not _has_value(hole.get("cuttingSize")):
                    cutting_size = _extract_cutting_size(evidence)
                    if cutting_size:
                        hole["cuttingSize"] = cutting_size

            key = (
                _clean_code(hole.get("normalizedCode")),
                _clean_text(hole.get("diameter")).lower(),
                _clean_text(hole.get("threadSize")).lower(),
                _clean_text(hole.get("tolerance")).lower(),
                _clean_text(hole.get("cuttingSize")).lower(),
            )
            if key not in index:
                index[key] = hole
                merged.append(hole)
                continue

            existing = index[key]
            existing_count = _int_count(existing.get("count"))
            new_count = _int_count(hole.get("count"))
            same_evidence = _clean_text(existing.get("evidence")) == evidence

            if same_evidence and max(existing_count, new_count) > 1:
                existing["count"] = max(existing_count, new_count)
            else:
                existing["count"] = existing_count + new_count
            existing["evidence"] = _merge_text(
                existing.get("evidence"), hole.get("evidence")
            )
            existing["notes"] = _merge_text(existing.get("notes"), hole.get("notes"))

        item["holes"] = merged


def _hole_type_for_code(code: str) -> str:
    return {
        "TAP": "tapped",
        "REAM": "reamed",
        "COUNTERSINK": "countersunk",
        "COUNTERBORE": "counterbore",
    }.get(code, "normal")


def _operation_for_code(code: str) -> str:
    return {
        "DRILL": "drilling",
        "TAP": "tapping",
        "REAM": "reaming",
        "FIT_HOLE": "hole fit",
        "COUNTERSINK": "countersinking",
        "COUNTERBORE": "counterboring",
        "DEBURR": "deburring",
        "MILL": "milling",
        "TURN": "turning",
        "WELD": "welding",
        "SURFACE_TREATMENT": "surface treatment",
        "HEAT_TREATMENT": "heat treatment",
    }.get(code, code.lower())


def _target_field_for_code(code: str) -> str | None:
    if code in HOLE_OPERATION_CODES:
        return "Borengaten"
    if code == "SURFACE_TREATMENT":
        return "surfaceTreatment"
    return None


def _extract_count(raw_value: str) -> int | None:
    match = re.search(r"(?i)(?:^|\D)(\d+)\s*x|x\s*(\d+)|\((\d+)\s*x\)", raw_value)
    if not match:
        return None
    for group in match.groups():
        if group:
            return _int_count(group)
    return None


def _extract_diameter(raw_value: str) -> str:
    match = re.search(r"(?:Ø|⌀|O)\s*([0-9]+(?:[.,][0-9]+)?)", raw_value)
    return match.group(1).replace(",", ".") if match else ""


def _extract_thread_size(raw_value: str) -> str:
    match = re.search(r"(?i)\bM\s*([0-9]+(?:[.,][0-9]+)?)\b", raw_value)
    return f"M{match.group(1).replace(',', '.')}" if match else ""


def _extract_cutting_size(raw_value: str) -> str:
    match = re.search(
        r"(?i)cutting\s+size\s*(?:Ø|⌀|O)?\s*([0-9]+(?:[.,][0-9]+)?)",
        raw_value,
    )
    return match.group(1).replace(",", ".") if match else ""


def _extract_hole_tolerance(raw_value: str) -> str:
    fit = re.search(
        r"(?i)(?:Ø|⌀|O)?\s*[0-9]+(?:[.,][0-9]+)?\s*([A-LN-Z][0-9]{1,2})\b",
        raw_value,
    )
    if not fit:
        fit = re.search(r"(?i)\b([A-LN-Z][0-9]{1,2})\b", raw_value)
    if fit:
        return fit.group(1).upper()
    plus_minus = re.search(
        r"([+-]\s*[0-9]+(?:[.,][0-9]+)?(?:\s*/\s*[+-]?\s*[0-9]+(?:[.,][0-9]+)?)?)",
        raw_value,
    )
    if plus_minus:
        return plus_minus.group(1).replace(" ", "").replace(",", ".")
    return ""


def _operation_key(operation: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        _clean_code(operation.get("normalizedCode")),
        _clean_text(operation.get("operation")).lower(),
        _clean_text(operation.get("diameter")).lower(),
        _clean_text(operation.get("threadSize")).lower(),
        _clean_text(operation.get("tolerance")).lower(),
        _clean_text(operation.get("cuttingSize")).lower(),
    )


def _signal_context_applies(
    signal: dict[str, Any], item: dict[str, Any], item_count: int
) -> bool:
    context = _clean_text(signal.get("context"))
    if not context and item_count == 1:
        return True
    part_number = _clean_text(item.get("partNumber"))
    return bool(part_number and part_number in context)


def backfill_operations_from_signals(data: dict[str, Any]) -> None:
    """Use mapping signals as an additional operation source."""

    items = [item for item in data.get("items") or [] if isinstance(item, dict)]
    for item in items:
        operations = [
            operation
            for operation in item.get("machiningOperations") or []
            if isinstance(operation, dict)
        ]
        operation_keys = {_operation_key(operation) for operation in operations}

        for signal in data.get("detectedSignals") or []:
            if not isinstance(signal, dict):
                continue
            code = _clean_code(signal.get("category"))
            raw_value = _clean_text(signal.get("rawValue"))
            if not _has_value(raw_value) or code not in HOLE_OPERATION_CODES | {
                "DEBURR",
                "MILL",
                "TURN",
                "WELD",
                "SURFACE_TREATMENT",
                "HEAT_TREATMENT",
            }:
                continue
            if not _signal_context_applies(signal, item, len(items)):
                continue

            operation: dict[str, Any] = {
                "normalizedCode": code,
                "operation": _operation_for_code(code),
                "targetField": _target_field_for_code(code),
                "evidence": raw_value,
            }
            count = _extract_count(raw_value)
            if count is not None:
                operation["count"] = count
            diameter = _extract_diameter(raw_value)
            if diameter:
                operation["diameter"] = diameter
            thread_size = _extract_thread_size(raw_value)
            if thread_size:
                operation["threadSize"] = thread_size
            tolerance = _extract_hole_tolerance(raw_value)
            if tolerance:
                operation["tolerance"] = tolerance
            cutting_size = _extract_cutting_size(raw_value)
            if cutting_size:
                operation["cuttingSize"] = cutting_size
            if code in HOLE_OPERATION_CODES and count is None:
                operation["notes"] = (
                    "Count not explicit in detected signal; verify against drawing or STEP geometry."
                )

            key = _operation_key(operation)
            if key in operation_keys:
                continue
            operation_keys.add(key)
            operations.append(operation)

        if operations:
            item["machiningOperations"] = operations


def backfill_holes_from_operations(data: dict[str, Any]) -> None:
    """Use structured operation signals as hole rows when Gemini omitted holes."""

    for item in data.get("items") or []:
        existing_holes = [
            hole for hole in item.get("holes") or [] if isinstance(hole, dict)
        ]
        hole_keys = {
            (
                _clean_code(hole.get("normalizedCode")),
                _clean_text(hole.get("diameter")).lower(),
                _clean_text(hole.get("threadSize")).lower(),
                _clean_text(hole.get("tolerance")).lower(),
                _clean_text(hole.get("cuttingSize")).lower(),
            )
            for hole in existing_holes
        }
        holes: list[dict[str, Any]] = []
        for operation in item.get("machiningOperations") or []:
            if not isinstance(operation, dict):
                continue
            code = _clean_code(operation.get("normalizedCode"))
            if code not in HOLE_OPERATION_CODES:
                continue
            key = (
                code,
                _clean_text(operation.get("diameter")).lower(),
                _clean_text(operation.get("threadSize")).lower(),
                _clean_text(operation.get("tolerance")).lower(),
                _clean_text(operation.get("cuttingSize")).lower(),
            )
            if key in hole_keys:
                continue
            hole_keys.add(key)
            holes.append(
                {
                    "count": operation.get("count"),
                    "normalizedCode": code,
                    "type": _hole_type_for_code(code),
                    "operation": operation.get("operation"),
                    "diameter": operation.get("diameter"),
                    "threadSize": operation.get("threadSize"),
                    "tolerance": operation.get("tolerance"),
                    "cuttingSize": operation.get("cuttingSize"),
                    "evidence": operation.get("evidence"),
                    "notes": operation.get("notes"),
                }
            )
        if holes:
            item["holes"] = existing_holes + holes


def backfill_item_fields_from_signals(data: dict[str, Any]) -> None:
    """Use explicit mapping signals as conservative item-level fallbacks."""

    material = ""
    surface_treatment = ""
    for signal in data.get("detectedSignals") or []:
        if not isinstance(signal, dict):
            continue
        category = _clean_code(signal.get("category"))
        raw_value = _clean_text(signal.get("rawValue"))
        if raw_value in {"", "None", "none", "null"}:
            continue
        if category == "MATERIAL" and not material:
            material = raw_value
        elif category == "SURFACE_TREATMENT" and not surface_treatment:
            surface_treatment = raw_value

    for item in data.get("items") or []:
        if material and not _clean_text(item.get("material")):
            item["material"] = material
        if surface_treatment and not _clean_text(item.get("surfaceTreatment")):
            item["surfaceTreatment"] = surface_treatment


def append_detected_signal(
    signals: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    category: str,
    raw_value: Any,
    context: Any = None,
) -> None:
    """Append a mapping signal once."""

    category = _clean_code(category)
    raw_text = _clean_text(raw_value)
    if not category or not _has_value(raw_text):
        return
    key = (category, raw_text)
    if key in seen:
        return
    seen.add(key)
    signals.append(
        {
            "category": category,
            "rawValue": raw_text,
            "page": 1,
            "source": "vision",
            "context": _clean_text(context),
        }
    )


def backfill_detected_signals(data: dict[str, Any]) -> None:
    """Create mapping-ready signals from structured features."""

    signals = [
        signal
        for signal in data.get("detectedSignals") or []
        if isinstance(signal, dict)
        and _clean_code(signal.get("category"))
        and _has_value(signal.get("rawValue"))
    ]
    seen = {
        (_clean_code(signal.get("category")), _clean_text(signal.get("rawValue")))
        for signal in signals
        if isinstance(signal, dict)
    }

    for item in data.get("items") or []:
        append_detected_signal(
            signals,
            seen,
            category="MATERIAL",
            raw_value=item.get("material"),
            context=item.get("partNumber"),
        )
        append_detected_signal(
            signals,
            seen,
            category="SURFACE_TREATMENT",
            raw_value=item.get("surfaceTreatment"),
            context=item.get("partNumber"),
        )
        for hole in item.get("holes") or []:
            if not isinstance(hole, dict):
                continue
            append_detected_signal(
                signals,
                seen,
                category=hole.get("normalizedCode") or hole.get("type") or "DRILL",
                raw_value=hole.get("evidence")
                or hole.get("threadSize")
                or hole.get("diameter"),
                context=item.get("partNumber"),
            )
        for operation in item.get("machiningOperations") or []:
            if not isinstance(operation, dict):
                continue
            append_detected_signal(
                signals,
                seen,
                category=operation.get("normalizedCode") or operation.get("operation"),
                raw_value=operation.get("evidence") or operation.get("operation"),
                context=item.get("partNumber"),
            )

    if signals:
        data["detectedSignals"] = signals


def build_tolerated_length_instructions(config: CustomerConfig) -> str:
    """Build tolerated length instructions from config."""
    if not config.signals or not config.signals.tolerated_lengths:
        return "          - Note: No special length patterns defined."

    lines = []
    for i, signal in enumerate(config.signals.tolerated_lengths):
        pattern = signal.pattern or "unknown pattern"
        desc = (
            signal.description
            or "treat as critical tolerance, add to toleratedLengths."
        )
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
        diameter = (
            f", diameter={hole.capture['diameter']}"
            if hole.capture and hole.capture.get("diameter")
            else ""
        )
        thread = (
            f", threadSize={hole.capture['threadSize']}"
            if hole.capture and hole.capture.get("threadSize")
            else ""
        )
        tolerance = (
            f", tolerance='{hole.capture['tolerance']}'"
            if hole.capture and hole.capture.get("tolerance")
            else ""
        )
        lines.append(
            f'          - Recipe {i + 1}: When you see "{pattern}", '
            f"set type='{h_type}'{diameter}{thread}{tolerance}."
        )

    return "\n".join(lines)


def build_surface_treatment_instructions(
    config: CustomerConfig, customer_name: str
) -> str:
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

    material_rules = [
        r.strip() for r in material_rules if isinstance(r, str) and r.strip()
    ]

    if not material_rules:
        return "          - Note: No special material patterns defined."

    return "\n".join(f"          - {rule}" for rule in material_rules)


async def extract_order_details_from_pdf(
    pdf_base64: str,
    options: ExtractionOptions | None = None,
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
    expected_part_number = options.expected_part_number
    model_name = options.model
    is_assembly = options.is_assembly
    technical_analysis = options.technical_analysis

    # Load customer config
    config = load_customer_config(customer_id)
    customer_name = config.customer_name or customer_id.upper()

    # Build instruction strings
    max_signal_entries = get_max_signal_prompt_entries(config)
    text_signals_section, _ = build_text_signals_section(
        text_signals, max_signal_entries
    )

    tolerated_length_instructions = build_tolerated_length_instructions(config)
    hole_instructions = build_hole_instructions(config)
    surface_treatment_instructions = build_surface_treatment_instructions(
        config, customer_name
    )
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
    if technical_analysis:
        prompt = build_technical_assembly_prompt(
            customer_name,
            surface_treatment_instructions,
        )
    elif is_assembly:
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
            top_p=1.0,
            top_k=1,
            max_output_tokens=8192,
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

    # Validate Gemini's JSON before applying any local mapping or fallback.  A
    # second validation below protects the final, post-processed contract.
    raw_order_details = OrderDetails(**data)
    data = raw_order_details.model_dump(by_alias=True, exclude_none=True)

    # The STEP match is authoritative for identity.  The PDF filename remains
    # available separately in ProcessingMetadata for provenance.
    part_number = expected_part_number or pdf_filename or "unknown_part_1"
    if "items" in data:
        for item in data["items"]:
            item["partNumber"] = part_number

    # Post-process surface treatment
    if "items" in data:
        for item in data["items"]:
            normalized = normalize_surface_treatment(item.get("surfaceTreatment"))
            fixed = apply_customer_surface_treatment_fixes(
                customer_id, normalized, is_assembly
            )
            if fixed != normalized:
                item["surfaceTreatment"] = fixed or "None"

    merge_duplicate_items(data)
    backfill_item_fields_from_signals(data)
    backfill_operations_from_signals(data)
    normalize_machining_operations(data)
    backfill_holes_from_operations(data)
    normalize_holes(data)
    filter_additional_pdf_features(data)
    backfill_detected_signals(data)

    # Keep OCR signals only when Gemini verified the same evidence. OCR cues are
    # hints, not an independent source of manufacturing truth.
    if text_signals:
        verified_keys = {
            (_clean_code(signal.get("category")), _clean_text(signal.get("rawValue")))
            for signal in data.get("detectedSignals") or []
            if isinstance(signal, dict)
        }
        signals = data.setdefault("detectedSignals", [])
        for text_signal in text_signals:
            signal = text_signal.model_dump(by_alias=True, exclude_none=True)
            key = (
                _clean_code(signal.get("category")),
                _clean_text(signal.get("rawValue")),
            )
            if key in verified_keys:
                signals.append(signal)

    # Create OrderDetails model
    order_details = OrderDetails(**data)

    return order_details


# Synchronous wrapper for simpler usage
def extract_order_details_from_pdf_sync(
    pdf_base64: str,
    options: ExtractionOptions | None = None,
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
            future = executor.submit(
                asyncio.run, extract_order_details_from_pdf(pdf_base64, options)
            )
            return future.result()
    else:
        return asyncio.run(extract_order_details_from_pdf(pdf_base64, options))
