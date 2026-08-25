"""Small SQLite job ledger for POC idempotency and status lookup."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class JobRecord:
    fingerprint: str
    job_id: str
    status: str
    result_path: str
    erp_draft_path: str | None


class JobStore:
    """Persist job state so the same message cannot create two ERP drafts."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        fingerprint TEXT PRIMARY KEY,
                        job_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        result_path TEXT NOT NULL,
                        erp_draft_path TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, fingerprint: str) -> JobRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT fingerprint, job_id, status, result_path, erp_draft_path
                FROM jobs WHERE fingerprint = ?
                """,
                (fingerprint,),
            ).fetchone()
        return JobRecord(*row) if row else None

    def start(self, *, fingerprint: str, job_id: str, result_path: Path) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        fingerprint, job_id, status, result_path,
                        erp_draft_path, created_at, updated_at
                    ) VALUES (?, ?, 'PROCESSING', ?, NULL, ?, ?)
                    """,
                    (fingerprint, job_id, str(result_path), now, now),
                )

    def finish(
        self,
        *,
        fingerprint: str,
        status: str,
        erp_draft_path: Path | None,
    ) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = ?, erp_draft_path = ?, updated_at = ?
                    WHERE fingerprint = ?
                    """,
                    (
                        status,
                        str(erp_draft_path) if erp_draft_path else None,
                        now,
                        fingerprint,
                    ),
                )
