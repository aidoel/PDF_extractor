"""Extractor and ERP adapter boundaries used by the proof of concept."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from json import JSONDecodeError
from pathlib import Path
from typing import Protocol

from .models import CanonicalPart, Evidence, ExtractedPart


class DocumentExtractor(Protocol):
    """Adapter contract for a manufacturing document extractor."""

    def extract(self, path: Path) -> list[ExtractedPart]: ...


def _read_poc_data(path: Path) -> dict[str, object]:
    """Read a JSON object following a POC-DATA marker in a test attachment."""

    text = path.read_bytes().decode("utf-8", errors="ignore")
    marker = "POC-DATA:"
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError(f"{path.name}: POC-DATA marker ontbreekt")
    candidate = text[marker_index + len(marker) :].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(candidate)
    except JSONDecodeError as exc:
        raise ValueError(f"{path.name}: ongeldige POC-DATA JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: POC-DATA moet een object zijn")
    return value


class PocPdfExtractor:
    """Deterministic PDF adapter for a local test email."""

    def extract(self, path: Path) -> list[ExtractedPart]:
        data = _read_poc_data(path)
        return [_part_from_poc(data, path, "pdf", "poc-pdf-v1")]


class PocStepExtractor:
    """Deterministic STEP adapter for a local test email."""

    def extract(self, path: Path) -> list[ExtractedPart]:
        data = _read_poc_data(path)
        return [_part_from_poc(data, path, "step", "poc-step-v1")]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _part_from_poc(
    data: dict[str, object],
    path: Path,
    source_type: str,
    extractor: str,
) -> ExtractedPart:
    part_number = str(data.get("part_number") or "").strip()
    if not part_number:
        raise ValueError(f"{path.name}: part_number ontbreekt")
    quantity_value = data.get("quantity")
    thickness_value = data.get("thickness_mm")
    return ExtractedPart(
        part_number=part_number,
        quantity=int(quantity_value) if quantity_value is not None else None,
        material=_optional_text(data.get("material")),
        thickness_mm=(
            float(thickness_value) if thickness_value is not None else None
        ),
        surface_treatment=_optional_text(data.get("surface_treatment")),
        evidence=Evidence(
            source_type=source_type,
            source_file=path.name,
            extractor=extractor,
        ),
    )


class MockAlesErp:
    """Write a reviewable draft instead of connecting to alesERP."""

    def create_draft(
        self,
        *,
        target: Path,
        job_id: str,
        message_id: str,
        sender: str,
        subject: str,
        parts: list[CanonicalPart],
    ) -> Path:
        payload = {
            "adapter": "mock-aleserp-v1",
            "mode": "DRAFT_ONLY",
            "external_reference": job_id,
            "source": {
                "message_id": message_id,
                "sender": sender,
                "subject": subject,
            },
            "parts": [asdict(part) for part in parts],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, target)
        return target

