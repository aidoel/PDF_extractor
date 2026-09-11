from extractor.gemini_service import (
    ORDER_DETAILS_SCHEMA,
    backfill_detected_signals,
    backfill_holes_from_operations,
    backfill_item_fields_from_signals,
    backfill_operations_from_signals,
    filter_additional_pdf_features,
    merge_duplicate_items,
    normalize_holes,
    normalize_machining_operations,
)
from extractor.prompt_builder import PromptInput, build_minimal_prompt
from extractor.types import OrderDetails
from extractor.xml_writer import build_simple_order_xml


def test_prompt_requires_mapping_ready_manufacturing_features() -> None:
    prompt = build_minimal_prompt(
        PromptInput(
            customer_name="BASE",
            images_count=1,
            tolerated_length_instructions="- test",
            hole_instructions="- test",
            surface_treatment_instructions="- test",
            material_instructions="- test",
        )
    )

    assert "NORMALIZED CODES FOR MAPPING" in prompt
    assert "REAM" in prompt
    assert "FIT_HOLE" in prompt
    assert "machiningOperations" in prompt
    assert "detectedSignals" in prompt
    assert "targetField=Borengaten" in prompt
    assert "Do not return BEND" in prompt
    assert "plain diameter" in prompt
    assert "- BEND:" not in prompt


def test_filter_removes_step_geometry_and_threaded_rod_false_positive() -> None:
    data = {
        "items": [
            {
                "partNumber": "MD-20-07032_1",
                "description": "Assembly with two threaded rods",
                "bomItems": [
                    {
                        "partNumber": "M16-ROD",
                        "description": "Threaded rod DIN 976-1 M16",
                    }
                ],
                "machiningOperations": [
                    {"normalizedCode": "BEND", "evidence": "bend angle 15°"},
                    {"normalizedCode": "TURN", "evidence": "Ø25 h6"},
                    {"normalizedCode": "DRILL", "evidence": "Ø12.5"},
                    {"normalizedCode": "TAP", "evidence": "M16"},
                    {"normalizedCode": "DEBURR", "evidence": "Break sharp edges"},
                ],
                "holes": [
                    {"normalizedCode": "DRILL", "evidence": "Ø12.5"},
                    {"normalizedCode": "TAP", "evidence": "M16"},
                ],
            }
        ],
        "detectedSignals": [
            {"category": "BEND", "rawValue": "bend angle 15°"},
            {"category": "TURN", "rawValue": "Ø25 h6"},
            {"category": "DRILL", "rawValue": "Ø12.5"},
            {"category": "TAP", "rawValue": "M16"},
            {"category": "DEBURR", "rawValue": "Break sharp edges"},
        ],
    }

    filter_additional_pdf_features(data)

    item = data["items"][0]
    assert [row["normalizedCode"] for row in item["machiningOperations"]] == ["DEBURR"]
    assert item["holes"] == []
    assert [row["category"] for row in data["detectedSignals"]] == [
        "TOLERANCE",
        "DEBURR",
    ]
    assert data["items"][0]["toleratedLengths"] == [
        {
            "dimension": "Ø25 h6",
            "toleranceType": "shaft_fit",
            "relatedFeature": "shaft",
            "evidence": "Ø25 h6",
        }
    ]


def test_filter_keeps_explicit_additional_manufacturing_instructions() -> None:
    data = {
        "items": [
            {
                "partNumber": "10040853_1",
                "machiningOperations": [
                    {"normalizedCode": "TAP", "evidence": "4x M6 tapped holes"},
                    {"normalizedCode": "REAM", "evidence": "2x ruim Ø20 H7"},
                    {"normalizedCode": "COUNTERSINK", "evidence": "DIN 74 countersink"},
                    {"normalizedCode": "DRILL", "evidence": "4 gaten boren Ø8"},
                    {"normalizedCode": "MILL", "evidence": "vlak frezen"},
                    {
                        "normalizedCode": "HEAT_TREATMENT",
                        "evidence": "spanningsarm gloeien",
                    },
                    {"normalizedCode": "BEND", "evidence": "zetten 90°"},
                ],
                "holes": [
                    {"normalizedCode": "TAP", "evidence": "4x M6 tapped holes"},
                    {"normalizedCode": "REAM", "evidence": "2x ruim Ø20 H7"},
                    {"normalizedCode": "FIT_HOLE", "evidence": "Ø12 H7"},
                ],
            }
        ],
        "detectedSignals": [
            {"category": "TAP", "rawValue": "4x M6 tapped holes"},
            {"category": "REAM", "rawValue": "2x ruim Ø20 H7"},
            {"category": "FIT_HOLE", "rawValue": "Ø12 H7"},
            {"category": "TOLERANCE", "rawValue": "Ø25 h6"},
            {"category": "SURFACE_TREATMENT", "rawValue": "poedercoaten RAL 7016"},
            {"category": "BEND", "rawValue": "zetten 90°"},
        ],
    }

    filter_additional_pdf_features(data)

    item = data["items"][0]
    assert {row["normalizedCode"] for row in item["machiningOperations"]} == {
        "TAP",
        "REAM",
        "COUNTERSINK",
        "DRILL",
        "MILL",
        "HEAT_TREATMENT",
    }
    assert {row["normalizedCode"] for row in item["holes"]} == {
        "TAP",
        "REAM",
        "FIT_HOLE",
    }
    assert {row["category"] for row in data["detectedSignals"]} == {
        "TAP",
        "REAM",
        "FIT_HOLE",
        "TOLERANCE",
        "SURFACE_TREATMENT",
    }


def test_schema_allows_structured_holes_and_operations() -> None:
    item_schema = ORDER_DETAILS_SCHEMA["properties"]["items"]["items"]["properties"]

    hole_properties = item_schema["holes"]["items"]["properties"]
    assert "normalizedCode" in hole_properties
    assert "cuttingSize" in hole_properties
    assert "upperTolerance" in hole_properties
    assert "evidence" in hole_properties

    operation_properties = item_schema["machiningOperations"]["items"]["properties"]
    assert "normalizedCode" in operation_properties
    assert "operation" in operation_properties
    assert "targetField" in operation_properties
    assert "evidence" in operation_properties


def test_xml_keeps_holes_operations_and_evidence() -> None:
    data = OrderDetails(
        detectedSignals=[
            {
                "category": "REAM",
                "rawValue": "Reaming O20H9 / Cutting Size O19.5",
                "page": 1,
                "source": "vision",
            }
        ],
        items=[
            {
                "partNumber": "10041870_1",
                "description": "Sheet",
                "material": "S235",
                "surfaceTreatment": "None",
                "holes": [
                    {
                        "count": 2,
                        "normalizedCode": "REAM",
                        "type": "reamed",
                        "operation": "reaming",
                        "diameter": "20",
                        "tolerance": "H9",
                        "cuttingSize": "19.5",
                        "evidence": "Reaming O20H9 / Cutting Size O19.5",
                    },
                    {
                        "count": 4,
                        "normalizedCode": "TAP",
                        "type": "tapped",
                        "threadSize": "M6",
                        "evidence": "M6(4x)",
                    },
                    {
                        "count": 2,
                        "normalizedCode": "FIT_HOLE",
                        "diameter": "40",
                        "upperTolerance": "+0.6",
                        "lowerTolerance": "+0.1",
                        "evidence": "O40 +0.6/+0.1",
                    },
                ],
                "machiningOperations": [
                    {
                        "normalizedCode": "REAM",
                        "operation": "reaming",
                        "targetField": "Borengaten",
                        "count": 2,
                        "diameter": "20",
                        "tolerance": "H9",
                        "cuttingSize": "19.5",
                        "evidence": "Reaming O20H9 / Cutting Size O19.5",
                    },
                    {
                        "normalizedCode": "TAP",
                        "operation": "tapping",
                        "targetField": "Borengaten",
                        "count": 4,
                        "threadSize": "M6",
                        "evidence": "M6(4x)",
                    },
                ],
            }
        ],
    )

    xml = build_simple_order_xml(data)

    assert "<Material>S235</Material>" in xml
    assert "<DetectedSignals>" in xml
    assert 'category="REAM"' in xml
    assert 'rawValue="Reaming O20H9 / Cutting Size O19.5"' in xml
    assert "<Holes>" in xml
    assert 'normalizedCode="REAM"' in xml
    assert 'cuttingSize="19.5"' in xml
    assert 'normalizedCode="TAP"' in xml
    assert 'threadSize="M6"' in xml
    assert 'normalizedCode="FIT_HOLE"' in xml
    assert 'upperTolerance="+0.6"' in xml
    assert "<MachiningOperations>" in xml
    assert 'targetField="Borengaten"' in xml
    assert "<Evidence>Reaming O20H9 / Cutting Size O19.5</Evidence>" in xml


def test_post_processing_derives_holes_and_mapping_signals_from_operations() -> None:
    data = {
        "items": [
            {
                "partNumber": "10041870_1",
                "machiningOperations": [
                    {
                        "normalizedCode": "REAM",
                        "operation": "reaming",
                        "targetField": "Borengaten",
                        "count": 1,
                        "diameter": "20",
                        "tolerance": "H9",
                        "cuttingSize": "19.5",
                        "evidence": "Reaming O20H9 / Cutting Size O19.5",
                    },
                    {
                        "normalizedCode": "REAM",
                        "operation": "reaming",
                        "targetField": "Borengaten",
                        "count": 1,
                        "diameter": "20",
                        "tolerance": "H9",
                        "cuttingSize": "19.5",
                        "evidence": "Reaming O20H9 / Cutting Size O19.5",
                    },
                    {
                        "normalizedCode": "TAP",
                        "operation": "tapping",
                        "targetField": "Borengaten",
                        "count": 4,
                        "threadSize": "M6",
                        "evidence": "M6(4x)",
                    },
                ],
            }
        ]
    }

    normalize_machining_operations(data)
    backfill_holes_from_operations(data)
    backfill_detected_signals(data)

    item = data["items"][0]
    assert item["machiningOperations"][0]["count"] == 2
    assert item["holes"][0]["normalizedCode"] == "REAM"
    assert item["holes"][0]["type"] == "reamed"
    assert item["holes"][0]["count"] == 2
    assert item["holes"][1]["normalizedCode"] == "TAP"
    assert item["holes"][1]["type"] == "tapped"
    assert {signal["category"] for signal in data["detectedSignals"]} == {
        "REAM",
        "TAP",
    }


def test_post_processing_uses_mapping_signals_as_item_fallbacks() -> None:
    data = {
        "detectedSignals": [
            {
                "category": "MATERIAL",
                "rawValue": "S235",
                "source": "vision",
            },
            {
                "category": "SURFACE_TREATMENT",
                "rawValue": "",
                "source": "vision",
            },
        ],
        "items": [{"partNumber": "10041870_1"}],
    }

    backfill_item_fields_from_signals(data)
    backfill_detected_signals(data)

    assert data["items"][0]["material"] == "S235"
    assert "surfaceTreatment" not in data["items"][0]
    assert data["detectedSignals"] == [
        {
            "category": "MATERIAL",
            "rawValue": "S235",
            "source": "vision",
        }
    ]


def test_post_processing_creates_operations_from_detected_signals() -> None:
    data = {
        "detectedSignals": [
            {
                "category": "FIT_HOLE",
                "rawValue": "Ø40 +0.6/+0.1",
                "source": "vision",
            },
            {
                "category": "DRILL",
                "rawValue": "Ø12.5",
                "source": "vision",
            },
            {
                "category": "TAP",
                "rawValue": "M6(4x)",
                "source": "vision",
            },
        ],
        "items": [{"partNumber": "10041870_1"}],
    }

    backfill_operations_from_signals(data)
    normalize_machining_operations(data)
    backfill_holes_from_operations(data)
    normalize_holes(data)

    operations = data["items"][0]["machiningOperations"]
    assert {operation["normalizedCode"] for operation in operations} == {
        "FIT_HOLE",
        "DRILL",
        "TAP",
    }
    assert operations[0]["diameter"] == "40"
    assert operations[0]["tolerance"] == "+0.6/+0.1"
    assert operations[1]["diameter"] == "12.5"
    assert operations[2]["threadSize"] == "M6"
    assert operations[2]["count"] == 4
    assert len(data["items"][0]["holes"]) == 3


def test_post_processing_merges_signal_backfill_with_existing_operations() -> None:
    data = {
        "detectedSignals": [
            {
                "category": "TAP",
                "rawValue": "M6(4x)",
                "source": "vision",
            },
            {
                "category": "REAM",
                "rawValue": "Reaming Ø20H9 / Cutting Size Ø19.5",
                "source": "vision",
            },
        ],
        "items": [
            {
                "partNumber": "10041870_1",
                "machiningOperations": [
                    {
                        "normalizedCode": "TAP",
                        "operation": "tapping",
                        "count": 4,
                        "threadSize": "M6",
                        "evidence": "M6(4x)",
                    },
                    {
                        "normalizedCode": "REAM",
                        "operation": "reaming",
                        "count": 2,
                        "diameter": "20",
                        "tolerance": "H9",
                        "cuttingSize": "19.5",
                        "evidence": "Reaming Ø20H9 / Cutting Size Ø19.5",
                    },
                    {
                        "normalizedCode": "SURFACE_TREATMENT",
                        "operation": "surface treatment",
                    },
                ],
            }
        ],
    }

    backfill_operations_from_signals(data)
    normalize_machining_operations(data)
    backfill_holes_from_operations(data)

    operations = data["items"][0]["machiningOperations"]
    tap_operations = [
        operation for operation in operations if operation["normalizedCode"] == "TAP"
    ]
    ream_operations = [
        operation for operation in operations if operation["normalizedCode"] == "REAM"
    ]

    assert len(tap_operations) == 1
    assert tap_operations[0]["count"] == 4
    assert tap_operations[0]["threadSize"] == "M6"
    assert "tolerance" not in tap_operations[0]
    assert len(ream_operations) == 1
    assert ream_operations[0]["count"] == 2
    assert ream_operations[0]["tolerance"] == "H9"
    assert all(
        operation["normalizedCode"] != "SURFACE_TREATMENT" for operation in operations
    )
    assert {
        (hole["normalizedCode"], hole.get("threadSize"), hole.get("tolerance"))
        for hole in data["items"][0]["holes"]
    } == {("TAP", "M6", None), ("REAM", None, "H9")}


def test_post_processing_merges_duplicate_pdf_item_fragments() -> None:
    data = {
        "detectedSignals": [
            {
                "category": "FIT_HOLE",
                "rawValue": "Ø 40 +0.6/+0.1",
                "source": "vision",
            },
            {
                "category": "DRILL",
                "rawValue": "Ø 12.5",
                "source": "vision",
            },
        ],
        "items": [
            {
                "partNumber": "10041870_1",
                "description": "Sheet",
                "material": "S235",
                "machiningOperations": [
                    {
                        "normalizedCode": "TAP",
                        "operation": "tapping",
                        "count": 4,
                        "threadSize": "M6",
                        "evidence": "M6(4x)",
                    }
                ],
            },
            {
                "partNumber": "10041870_1",
                "material": "S235",
                "holes": [
                    {
                        "normalizedCode": "REAM",
                        "count": 1,
                        "diameter": "20",
                        "tolerance": "H9",
                        "cuttingSize": "19.5",
                        "evidence": "Reaming Ø20H9 Cutting Size Ø 19.5",
                    }
                ],
            },
        ],
    }

    merge_duplicate_items(data)
    backfill_operations_from_signals(data)
    normalize_machining_operations(data)
    backfill_holes_from_operations(data)
    normalize_holes(data)

    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["description"] == "Sheet"
    assert item["material"] == "S235"
    assert {
        (
            operation["normalizedCode"],
            operation.get("diameter"),
            operation.get("threadSize"),
        )
        for operation in item["machiningOperations"]
    } == {
        ("TAP", None, "M6"),
        ("FIT_HOLE", "40", None),
        ("DRILL", "12.5", None),
    }
    assert {
        (hole["normalizedCode"], hole.get("diameter"), hole.get("threadSize"))
        for hole in item["holes"]
    } == {
        ("REAM", "20", None),
        ("TAP", None, "M6"),
        ("FIT_HOLE", "40", None),
        ("DRILL", "12.5", None),
    }
