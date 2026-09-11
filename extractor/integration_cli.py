"""Machine-readable single-PDF entry point for the hybrid orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .main import extract_routed_pdf
from .types import ProcessingMetadata
from .xml_writer import build_simple_order_xml

INTEGRATION_SCHEMA_VERSION = "1.0"


def emit(event: str, **payload: Any) -> None:
    print(
        json.dumps(
            {"schema_version": INTEGRATION_SCHEMA_VERSION, "event": event, **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


def _unique(values: list[str], limit: int = 8) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.casefold()
        if (
            not cleaned
            or key in {"none", "null", "n/a", "na", "geen", "-"}
            or key in seen
        ):
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _display_value(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(?<=\d)\.(?=\d)", ",", text)
    text = re.sub(r"^[Ø⌀]\s*", "diameter ", text)
    return text.replace("°", " graden")


def _optional_text(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.casefold() in {"none", "null", "n/a", "na", "geen", "-"} else text


def _operation_text(operation: object) -> str:
    if isinstance(operation, str):
        return operation.strip()
    name = _optional_text(getattr(operation, "operation", None))
    code = _optional_text(getattr(operation, "normalized_code", None))
    evidence = _optional_text(getattr(operation, "evidence", None))
    notes = _optional_text(getattr(operation, "notes", None))
    count = getattr(operation, "count", None)
    cutting_size = _optional_text(getattr(operation, "cutting_size", None))
    if (
        code.upper() == "WELD"
        and "general agreements for welded assemblies" in evidence.casefold()
    ):
        source = notes.casefold()
        instructions: list[str] = []
        if "tube frames + end plates welded on all sides" in source:
            instructions.append("frame en eindplaten rondom lassen")
        if "weld 50 [mm], 100 [mm] free" in source:
            instructions.append("plaatlassen 50 mm lassen/100 mm vrij")
        if "keep holes free of welds" in source:
            instructions.append("gaten vrijhouden van lassen")
        if instructions:
            return "; ".join(instructions)
    if code.upper() == "DEBURR" and cutting_size:
        prefix = f"{count} x " if count and count > 1 else ""
        return f"{prefix}afschuining {_display_value(cutting_size)}"
    if code.upper() == "DEBURR":
        deburr_evidence = evidence.casefold().rstrip(".")
        if deburr_evidence.startswith("break sharp edges"):
            result = "scherpe kanten breken"
            if "retaining ring grooves sharp" in deburr_evidence:
                result += "; borgringgroeven scherp houden"
            return result
        if deburr_evidence.startswith("scherpe kanten breken"):
            return evidence.rstrip(".")
    if evidence:
        detail = evidence
        if notes and notes.casefold() not in evidence.casefold():
            detail = f"{detail}: {notes}"
        return _display_value(detail)
    return _display_value(name or code)


def _hole_annotation_text(hole: object) -> str:
    evidence = str(getattr(hole, "evidence", None) or "").strip()
    if evidence:
        return _display_value(evidence)
    count = getattr(hole, "count", None)
    operation = str(
        getattr(hole, "operation", None)
        or getattr(hole, "type", None)
        or getattr(hole, "normalized_code", None)
        or "gat"
    ).strip()
    size = str(
        getattr(hole, "thread_size", None) or getattr(hole, "diameter", None) or ""
    ).strip()
    tolerance = str(getattr(hole, "tolerance", None) or "").strip()
    depth = str(getattr(hole, "depth", None) or "").strip()
    details = " ".join(value for value in (operation, size, tolerance) if value)
    if depth:
        details = f"{details}, diepte {depth}" if details else f"diepte {depth}"
    if count and count > 1:
        return _display_value(f"{count} x {details or 'gat'}")
    return _display_value(details or "gat")


def _tolerance_text(tolerance: object) -> str:
    dimension = _optional_text(getattr(tolerance, "dimension", None))
    upper = _optional_text(getattr(tolerance, "upper_tolerance", None))
    lower = _optional_text(getattr(tolerance, "lower_tolerance", None))
    if dimension and upper and lower:
        return f"{dimension} {upper}/{lower}"
    evidence = _optional_text(getattr(tolerance, "evidence", None))
    if evidence:
        return evidence
    return " ".join(value for value in (dimension, upper, lower) if value)


def _tolerance_result_text(tolerance: object) -> str:
    value = _display_value(_tolerance_text(tolerance))
    tolerance_type = str(getattr(tolerance, "tolerance_type", None) or "").casefold()
    prefix = "aspassing:" if tolerance_type == "shaft_fit" else "lengtetolerantie"
    return f"{prefix} {value}" if value else ""


def build_analysis_text(data, *, gemini_used: bool) -> str:
    """Build browser text from PDF facts that add to STEP geometry."""

    materials: list[str] = []
    treatments: list[str] = []
    operations: list[str] = []
    hole_annotations: list[str] = []
    tolerances: list[str] = []
    signal_tolerances: list[str] = []
    roughness_requirements: list[str] = []
    structured_tolerance_values: set[str] = set()

    for item in data.items or []:
        materials.append(item.material or "")
        treatments.append(item.surface_treatment or "")
        for tolerance in item.tolerated_lengths or []:
            raw_value = _tolerance_text(tolerance)
            if raw_value:
                structured_tolerance_values.add(raw_value.casefold())
                evidence = _optional_text(getattr(tolerance, "evidence", None))
                if evidence:
                    structured_tolerance_values.add(evidence.casefold())
                tolerances.append(_tolerance_result_text(tolerance))
        for operation in item.machining_operations or []:
            code = str(getattr(operation, "normalized_code", None) or "").upper()
            if code not in {
                "BEND",
                "SURFACE_TREATMENT",
                "ROUGHNESS",
                "DRILL",
                "TAP",
                "REAM",
                "FIT_HOLE",
                "COUNTERSINK",
                "COUNTERBORE",
            }:
                operations.append(_operation_text(operation))
        hole_annotations.extend(
            _hole_annotation_text(hole) for hole in item.holes or []
        )

    for signal in data.detected_signals or []:
        category = str(signal.category or "").strip().upper()
        raw_value = str(signal.raw_value or "").strip()
        if (
            category == "TOLERANCE"
            and raw_value.casefold() not in structured_tolerance_values
        ):
            signal_tolerances.append(f"tolerantie {_display_value(raw_value)}")
        elif category == "ROUGHNESS":
            display_value = _display_value(raw_value)
            if display_value.casefold().startswith(("ruwheid", "ruwheden")):
                roughness_requirements.append(display_value)
            else:
                roughness_requirements.append(f"ruwheid {display_value}")

    parts: list[str] = []
    material_values = _unique(materials)
    if material_values:
        parts.append(
            f"materiaal {', '.join(_display_value(value) for value in material_values)}"
        )
    operation_values = _unique(operations)
    if operation_values:
        parts.extend(operation_values)
    hole_values = _unique(hole_annotations)
    if hole_values:
        parts.extend(hole_values)
    tolerance_values = _unique([*tolerances, *signal_tolerances])
    if tolerance_values:
        parts.extend(tolerance_values)
    roughness_values = _unique(roughness_requirements)
    if roughness_values:
        parts.extend(roughness_values)
    treatment_values = _unique(treatments)
    if treatment_values:
        parts.extend(_display_value(value) for value in treatment_values)

    return "; ".join(_unique(parts, limit=20))


def build_compact_summary(data, *, gemini_used: bool) -> dict[str, Any]:
    """Return browser-safe headline facts without duplicating the full XML."""

    materials: list[str] = []
    treatments: list[str] = []
    revisions: list[str] = []
    operations: list[str] = []
    risks: list[dict[str, str | None]] = []
    hole_count = 0
    tolerance_evidence: list[str] = []
    for item in data.items or []:
        materials.append(item.material or "")
        treatments.append(item.surface_treatment or "")
        revisions.append(item.revision or "")
        for hole in item.holes or []:
            hole_count += hole.count if hole.count is not None else 1
        tolerance_evidence.extend(
            _tolerance_text(tolerance) for tolerance in item.tolerated_lengths or []
        )
        for operation in item.machining_operations or []:
            if isinstance(operation, str):
                operations.append(operation)
            elif str(operation.normalized_code or "").upper() != "BEND":
                operations.append(
                    operation.normalized_code or operation.operation or ""
                )
        analysis = item.technical_analysis
        if analysis:
            for risk in analysis.risks:
                risks.append(
                    {
                        "severity": risk.severity,
                        "summary": risk.summary,
                    }
                )

    tolerance_evidence.extend(
        signal.raw_value or ""
        for signal in data.detected_signals or []
        if str(signal.category or "").strip().upper() == "TOLERANCE"
    )

    return {
        "mode": "gemini" if gemini_used else "preflight_only",
        "drawing_number": data.drawing_number,
        "drawing_title": data.drawing_title,
        "materials": _unique(materials),
        "surface_treatments": _unique(treatments),
        "revisions": _unique(revisions),
        "operations": _unique(operations),
        "hole_count": hole_count,
        "tolerance_count": len(_unique(tolerance_evidence)),
        "risks": risks[:3],
        "signal_categories": _unique(
            [signal.category for signal in data.detected_signals or []]
        ),
        "analysis_text": build_analysis_text(data, gemini_used=gemini_used),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one PDF extraction with JSONL progress events."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--xml", required=True, type=Path)
    parser.add_argument("--part-number", required=True)
    parser.add_argument("--part-id", required=True)
    parser.add_argument("--solid-index", required=True, type=int)
    parser.add_argument("--schema-version", default=INTEGRATION_SCHEMA_VERSION)
    parser.add_argument("--customer", default="base")
    parser.add_argument("--model")
    parser.add_argument(
        "--scan-depth", choices=("auto", "fast", "deep"), default="auto"
    )
    parser.add_argument("--match-strategy", default="")
    parser.add_argument("--match-confidence", type=float)
    parser.add_argument(
        "--gemini-policy",
        choices=("auto", "always", "vision_only", "never"),
        default="auto",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    package_root = Path(__file__).resolve().parents[1]
    load_dotenv(package_root / ".env")
    pdf_path = args.pdf.resolve()
    xml_path = args.xml.resolve()

    if args.schema_version != INTEGRATION_SCHEMA_VERSION:
        emit(
            "contract_rejected",
            message=(
                f"Unsupported integration schema {args.schema_version}; "
                f"expected {INTEGRATION_SCHEMA_VERSION}"
            ),
        )
        return 4

    if not pdf_path.is_file():
        emit("failed", message=f"PDF not found: {pdf_path}")
        return 2

    def status_callback(event: str, payload: dict[str, Any]) -> None:
        emit(
            event,
            part_id=args.part_id,
            solid_index=args.solid_index,
            part_name=args.part_number,
            pdf_path=str(pdf_path),
            **payload,
        )

    try:
        data, preflight, model, gemini_seconds = await extract_routed_pdf(
            pdf_path,
            customer_id=args.customer,
            scan_depth=args.scan_depth,
            requested_model=args.model,
            expected_part_number=args.part_number,
            status_callback=status_callback,
            gemini_policy=args.gemini_policy,
        )
        gemini_used = model != "none"
        success = any(item.status != "FAILED" for item in data.items)
        data.metadata = ProcessingMetadata(
            totalPDFs=1,
            successfulPDFs=1 if success else 0,
            failedPDFs=0 if success else 1,
            detectedCustomer=args.customer.upper(),
            sourcePDF=pdf_path.name,
            stepPartId=args.part_id,
            stepSolidIndex=args.solid_index,
            stepPartName=args.part_number,
            matchStrategy=args.match_strategy or None,
            matchConfidence=args.match_confidence,
            preflightKind=preflight.kind,
            preflightRoute=preflight.route,
            preflightConfidence=preflight.confidence,
            preflightMs=round(preflight.elapsed_ms, 3),
            geminiModel=model if gemini_used else None,
            geminiSeconds=round(gemini_seconds, 3),
        )
        # Final validation after mapping/post-processing and metadata enrichment.
        data = type(data).model_validate(data.model_dump(by_alias=True))
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(build_simple_order_xml(data), encoding="utf-8")
        emit(
            "completed",
            part_id=args.part_id,
            solid_index=args.solid_index,
            part_name=args.part_number,
            pdf_path=str(pdf_path),
            xml_path=str(xml_path),
            model=model,
            success=success,
            gemini_used=gemini_used,
            requires_review=preflight.route == "manual_review" and not gemini_used,
            summary=build_compact_summary(data, gemini_used=gemini_used),
        )
        return 0 if success else 3
    except Exception as exc:  # noqa: BLE001 - boundary reports a structured failure
        emit(
            "failed",
            part_id=args.part_id,
            solid_index=args.solid_index,
            part_name=args.part_number,
            pdf_path=str(pdf_path),
            error_type=type(exc).__name__,
            message=str(exc),
        )
        return 1


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
