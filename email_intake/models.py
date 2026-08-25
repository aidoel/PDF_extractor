"""Data structures shared by the email intake proof of concept."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IncomingAttachment:
    """A decoded attachment before it is persisted to a job directory."""

    filename: str
    content_type: str
    sha256: str
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class IncomingEmail:
    """Relevant metadata and supported attachments from an RFC 822 message."""

    message_id: str
    sender: str
    subject: str
    received_at: str
    fingerprint: str
    attachments: tuple[IncomingAttachment, ...]


@dataclass(frozen=True)
class StoredAttachment:
    """An attachment stored inside an immutable intake job directory."""

    filename: str
    content_type: str
    sha256: str
    path: Path


@dataclass(frozen=True)
class Evidence:
    """Traceability for one extractor result."""

    source_type: str
    source_file: str
    extractor: str


@dataclass(frozen=True)
class ExtractedPart:
    """Normalized result returned by either a PDF or STEP adapter."""

    part_number: str
    quantity: int | None = None
    material: str | None = None
    thickness_mm: float | None = None
    surface_treatment: str | None = None
    evidence: Evidence | None = None


@dataclass(frozen=True)
class FieldConflict:
    """A difference that must be resolved before an ERP draft is created."""

    part_number: str
    field: str
    pdf_value: Any
    step_value: Any
    message: str


@dataclass
class CanonicalPart:
    """Part assembled from all available evidence."""

    part_number: str
    quantity: int
    material: str | None
    thickness_mm: float | None
    surface_treatment: str | None
    sources: list[Evidence] = field(default_factory=list)


@dataclass
class IntakeResult:
    """User-facing result of processing one email."""

    job_id: str
    status: str
    duplicate: bool
    result_path: Path
    erp_draft_path: Path | None
    parts: list[CanonicalPart] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["result_path"] = str(self.result_path)
        data["erp_draft_path"] = (
            str(self.erp_draft_path) if self.erp_draft_path is not None else None
        )
        return data

