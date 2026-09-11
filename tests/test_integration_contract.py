from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from extractor.config_loader import find_config_root
from extractor.gemini_service import (
    backfill_detected_signals,
    normalize_holes,
    normalize_machining_operations,
)
from extractor.integration_cli import (
    INTEGRATION_SCHEMA_VERSION,
    build_compact_summary,
    run,
)
from extractor.main import should_run_gemini
from extractor.pdf_preflight import PdfPreflightResult
from extractor.types import ExtractionOptions, OrderDetails, ProcessingMetadata
from extractor.xml_writer import build_simple_order_xml


def test_package_config_wins_over_unrelated_working_directory(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "config").mkdir()
    monkeypatch.chdir(tmp_path)

    assert (find_config_root() / "base.yaml").is_file()


def test_expected_step_part_number_is_an_explicit_option() -> None:
    options = ExtractionOptions(
        pdfFilename="drawing-name",
        expectedPartNumber="STEP-PART-42",
    )

    assert options.pdf_filename == "drawing-name"
    assert options.expected_part_number == "STEP-PART-42"


def test_integration_metadata_is_written_to_xml() -> None:
    data = OrderDetails(
        items=[{"partNumber": "STEP-PART-42", "material": "S235"}],
        metadata=ProcessingMetadata(
            totalPDFs=1,
            successfulPDFs=1,
            failedPDFs=0,
            detectedCustomer="BASE",
            sourcePDF="drawing.pdf",
            stepPartId="solid-7",
            stepSolidIndex=7,
            stepPartName="STEP-PART-42",
            matchStrategy="exact_normalized",
            matchConfidence=1.0,
            preflightKind="text_native",
            preflightRoute="text_fast",
            preflightConfidence=0.95,
            preflightMs=12.5,
            geminiModel="gemini-test",
            geminiSeconds=1.25,
        ),
    )

    xml = build_simple_order_xml(data)

    assert "<PartNumber>STEP-PART-42</PartNumber>" in xml
    assert "<SourcePDF>drawing.pdf</SourcePDF>" in xml
    assert "<StepPartId>solid-7</StepPartId>" in xml
    assert "<StepSolidIndex>7</StepSolidIndex>" in xml
    assert "<MatchConfidence>1.0</MatchConfidence>" in xml
    assert "<GeminiModel>gemini-test</GeminiModel>" in xml


def test_integration_schema_version_is_explicit() -> None:
    assert INTEGRATION_SCHEMA_VERSION == "1.0"


def test_integration_rejects_unknown_request_schema(tmp_path: Path) -> None:
    args = argparse.Namespace(
        pdf=tmp_path / "missing.pdf",
        xml=tmp_path / "result.xml",
        part_number="P-1",
        part_id="solid-3",
        solid_index=3,
        schema_version="9.9",
    )

    assert asyncio.run(run(args)) == 4


def test_post_processing_can_be_followed_by_final_pydantic_validation() -> None:
    payload = {
        "items": [
            {
                "partNumber": "P-1",
                "machiningOperations": [
                    {
                        "normalizedCode": "TAP",
                        "operation": "tapping",
                        "threadSize": "M6",
                    }
                ],
            }
        ]
    }
    raw = OrderDetails(**payload).model_dump(by_alias=True, exclude_none=True)
    normalize_machining_operations(raw)
    normalize_holes(raw)
    backfill_detected_signals(raw)

    final = OrderDetails(**raw)

    assert final.items[0].machining_operations
    assert final.detected_signals


def _preflight(route: str) -> PdfPreflightResult:
    return PdfPreflightResult(
        kind="hybrid" if route == "vision_fast" else "text_native",
        route=route,
        complexity="moderate",
        confidence=0.9,
        page_count=1,
        pages_scanned=1,
        text_chars=100,
        alnum_chars=80,
        font_count=1,
        image_count=1,
        content_bytes=1000,
        text_operator_count=1,
        vector_operator_count=1,
        max_page_area_points=100.0,
        elapsed_ms=5.0,
        evidence="fixture",
    )


def test_gemini_policy_is_applied_after_preflight() -> None:
    assert should_run_gemini(_preflight("text_fast"), "auto") is True
    assert should_run_gemini(_preflight("manual_review"), "auto") is False
    assert should_run_gemini(_preflight("text_fast"), "vision_only") is False
    assert should_run_gemini(_preflight("vision_fast"), "vision_only") is True
    assert should_run_gemini(_preflight("vision_fast"), "never") is False


def test_compact_summary_contains_pdf_headline_results() -> None:
    data = OrderDetails(
        drawingNumber="D-42",
        items=[
            {
                "material": "S235",
                "surfaceTreatment": "powder coating",
                "revision": "B",
                "holes": [{"count": 3, "diameter": "6 mm"}],
                "toleratedLengths": [{"dimension": "20", "upperTolerance": "+0.1"}],
                "machiningOperations": [
                    {"normalizedCode": "TAP", "operation": "tapping"}
                ],
                "technicalAnalysis": {
                    "conclusion": "Controleer de expliciete M6 draadnotitie."
                },
            }
        ],
    )

    summary = build_compact_summary(data, gemini_used=True)

    assert summary["materials"] == ["S235"]
    assert summary["operations"] == ["TAP"]
    assert summary["hole_count"] == 3
    assert summary["tolerance_count"] == 1
    assert summary["analysis_text"] == (
        "materiaal S235; 3 x gat 6 mm; lengtetolerantie 20 +0,1; powder coating"
    )


def test_compact_summary_is_empty_when_light_finds_nothing() -> None:
    summary = build_compact_summary(OrderDetails(), gemini_used=False)

    assert summary["analysis_text"] == ""


def test_compact_summary_is_empty_when_gemini_finds_nothing() -> None:
    summary = build_compact_summary(OrderDetails(), gemini_used=True)

    assert summary["analysis_text"] == ""


def test_compact_summary_includes_mapping_tolerance_and_roughness_signals() -> None:
    data = OrderDetails(
        items=[{"partNumber": "10040878_1"}],
        detectedSignals=[
            {"category": "TOLERANCE", "rawValue": "90° ±0.5°"},
            {"category": "ROUGHNESS", "rawValue": "Ra 3.2"},
        ],
    )

    summary = build_compact_summary(data, gemini_used=True)

    assert summary["tolerance_count"] == 1
    assert summary["analysis_text"] == (
        "tolerantie 90 graden ±0,5 graden; ruwheid Ra 3,2"
    )


def test_compact_summary_does_not_repeat_roughness_label() -> None:
    data = OrderDetails(
        items=[{"partNumber": "P-1"}],
        detectedSignals=[
            {"category": "ROUGHNESS", "rawValue": "ruwheden volgens NEN 3632"}
        ],
    )

    summary = build_compact_summary(data, gemini_used=True)

    assert summary["analysis_text"] == "ruwheden volgens NEN 3632"


def test_compact_summary_includes_explicit_operation_notes() -> None:
    data = OrderDetails(
        items=[
            {
                "partNumber": "10040878_1",
                "machiningOperations": [
                    {
                        "normalizedCode": "WELD",
                        "operation": "welding",
                        "evidence": "General welding agreements",
                        "notes": "weld 50 mm, leave 100 mm free",
                    }
                ],
            }
        ]
    )

    summary = build_compact_summary(data, gemini_used=True)

    assert summary["analysis_text"] == (
        "General welding agreements: weld 50 mm, leave 100 mm free"
    )


def test_compact_summary_uses_terse_manufacturing_facts() -> None:
    data = OrderDetails(
        items=[
            {
                "machiningOperations": [
                    {
                        "normalizedCode": "DEBURR",
                        "count": 8,
                        "cuttingSize": "0.5x45°",
                        "evidence": "0.5x45° (8x)",
                    }
                ],
                "toleratedLengths": [
                    {
                        "dimension": "502",
                        "upperTolerance": "0",
                        "lowerTolerance": "-0.2",
                        "evidence": "502 0/-0.2",
                    },
                    {
                        "dimension": "Ø25 h6",
                        "toleranceType": "shaft_fit",
                        "evidence": "Ø25 h6",
                    },
                ],
                "surfaceTreatment": "bead blasted",
            }
        ]
    )

    summary = build_compact_summary(data, gemini_used=True)

    assert summary["analysis_text"] == (
        "8 x afschuining 0,5x45 graden; lengtetolerantie 502 0/-0,2; "
        "aspassing: diameter 25 h6; bead blasted"
    )


def test_compact_summary_ignores_placeholder_cutting_size() -> None:
    data = OrderDetails(
        items=[
            {
                "machiningOperations": [
                    {
                        "normalizedCode": "DEBURR",
                        "operation": "Deburring",
                        "cuttingSize": "None",
                        "evidence": "Break sharp edges, retaining ring grooves sharp",
                    }
                ]
            }
        ]
    )

    summary = build_compact_summary(data, gemini_used=True)

    assert "afschuining None" not in summary["analysis_text"]
    assert summary["analysis_text"] == (
        "scherpe kanten breken; borgringgroeven scherp houden"
    )


def test_compact_summary_shortens_standard_welding_instructions() -> None:
    data = OrderDetails(
        items=[
            {
                "machiningOperations": [
                    {
                        "normalizedCode": "WELD",
                        "evidence": "General agreements for welded assemblies unless otherwise indicated:",
                        "notes": (
                            "1. Tube frames + end plates welded on all sides "
                            "2. Sheet metal interrupted welding (weld 50 [mm], 100 [mm] free) "
                            "3. Keep holes free of welds"
                        ),
                    }
                ]
            }
        ]
    )

    summary = build_compact_summary(data, gemini_used=True)

    assert summary["analysis_text"] == (
        "frame en eindplaten rondom lassen; plaatlassen 50 mm lassen/100 mm vrij; "
        "gaten vrijhouden van lassen"
    )
