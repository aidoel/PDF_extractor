"""End-to-end orchestration for one local test email."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .adapters import DocumentExtractor, MockAlesErp, PocPdfExtractor, PocStepExtractor
from .mailbox import read_eml, store_attachments
from .models import FieldConflict, IntakeResult
from .reconcile import reconcile_parts
from .store import JobStore


class EmailIntakeService:
    """Process test emails through extraction, reconciliation and mock ERP."""

    def __init__(
        self,
        workspace: Path,
        *,
        pdf_extractor: DocumentExtractor | None = None,
        step_extractor: DocumentExtractor | None = None,
        erp: MockAlesErp | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.runs = self.workspace / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)
        self.store = JobStore(self.workspace / "jobs.sqlite3")
        self.pdf_extractor = pdf_extractor or PocPdfExtractor()
        self.step_extractor = step_extractor or PocStepExtractor()
        self.erp = erp or MockAlesErp()

    def process_eml(self, path: Path) -> IntakeResult:
        incoming = read_eml(path)
        existing = self.store.get(incoming.fingerprint)
        if existing:
            result_path = Path(existing.result_path)
            return IntakeResult(
                job_id=existing.job_id,
                status=existing.status,
                duplicate=True,
                result_path=result_path,
                erp_draft_path=(
                    Path(existing.erp_draft_path) if existing.erp_draft_path else None
                ),
                parts=[],
                conflicts=[],
            )

        job_id = incoming.fingerprint[:16]
        job_dir = self.runs / job_id
        result_path = job_dir / "result.json"
        job_dir.mkdir(parents=False, exist_ok=False)
        self.store.start(
            fingerprint=incoming.fingerprint,
            job_id=job_id,
            result_path=result_path,
        )

        shutil.copyfile(path, job_dir / "source.eml")
        attachments = store_attachments(incoming, job_dir / "attachments")
        pdf_parts = []
        step_parts = []
        for attachment in attachments:
            suffix = attachment.path.suffix.lower()
            if suffix == ".pdf":
                pdf_parts.extend(self.pdf_extractor.extract(attachment.path))
            elif suffix in {".step", ".stp"}:
                step_parts.extend(self.step_extractor.extract(attachment.path))

        parts, conflicts = reconcile_parts(pdf_parts, step_parts)
        if not pdf_parts:
            conflicts.append(
                _source_conflict("PDF", "Geen verwerkbare PDF-resultaten gevonden")
            )
        if not step_parts:
            conflicts.append(
                _source_conflict("STEP", "Geen verwerkbare STEP-resultaten gevonden")
            )

        erp_draft_path: Path | None = None
        status = "NEEDS_REVIEW" if conflicts else "READY_FOR_ERP"
        if not conflicts:
            erp_draft_path = self.erp.create_draft(
                target=job_dir / "mock-aleserp-draft.json",
                job_id=job_id,
                message_id=incoming.message_id,
                sender=incoming.sender,
                subject=incoming.subject,
                parts=parts,
            )

        payload = {
            "job_id": job_id,
            "status": status,
            "processed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "email": {
                "message_id": incoming.message_id,
                "sender": incoming.sender,
                "subject": incoming.subject,
                "received_at": incoming.received_at,
                "fingerprint": incoming.fingerprint,
            },
            "attachments": [
                {
                    "filename": attachment.filename,
                    "content_type": attachment.content_type,
                    "sha256": attachment.sha256,
                }
                for attachment in attachments
            ],
            "parts": [asdict(part) for part in parts],
            "conflicts": [asdict(conflict) for conflict in conflicts],
            "erp_draft_path": str(erp_draft_path) if erp_draft_path else None,
        }
        result_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.store.finish(
            fingerprint=incoming.fingerprint,
            status=status,
            erp_draft_path=erp_draft_path,
        )
        return IntakeResult(
            job_id=job_id,
            status=status,
            duplicate=False,
            result_path=result_path,
            erp_draft_path=erp_draft_path,
            parts=parts,
            conflicts=conflicts,
        )


def _source_conflict(source: str, message: str) -> FieldConflict:
    return FieldConflict(
        part_number="*",
        field="source",
        pdf_value=None if source == "PDF" else "available",
        step_value=None if source == "STEP" else "available",
        message=message,
    )
