"""Read test emails and persist only supported manufacturing attachments."""

from __future__ import annotations

import hashlib
import re
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path

from .models import IncomingAttachment, IncomingEmail, StoredAttachment


SUPPORTED_EXTENSIONS = {".pdf", ".step", ".stp"}
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENTS = 20
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


class EmailValidationError(ValueError):
    """Raised when a message cannot safely enter the intake pipeline."""


def _sanitize_filename(filename: str) -> str:
    leaf = Path(filename.replace("\\", "/")).name.strip()
    safe = _SAFE_FILENAME.sub("_", leaf).strip(" .")
    if not safe or safe in {".", ".."}:
        raise EmailValidationError("Bijlage heeft geen veilige bestandsnaam")
    return safe


def read_eml(path: Path) -> IncomingEmail:
    """Parse an RFC 822 file and calculate an idempotency fingerprint."""

    raw = path.read_bytes()
    message = BytesParser(policy=policy.default).parsebytes(raw)
    attachments: list[IncomingAttachment] = []

    for part in message.iter_attachments():
        filename = part.get_filename()
        if not filename:
            continue
        safe_name = _sanitize_filename(filename)
        if Path(safe_name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True) or b""
        if len(payload) > MAX_ATTACHMENT_BYTES:
            raise EmailValidationError(
                f"Bijlage {safe_name} is groter dan {MAX_ATTACHMENT_BYTES} bytes"
            )
        attachments.append(
            IncomingAttachment(
                filename=safe_name,
                content_type=part.get_content_type(),
                sha256=hashlib.sha256(payload).hexdigest(),
                payload=payload,
            )
        )

    if len(attachments) > MAX_ATTACHMENTS:
        raise EmailValidationError(f"Meer dan {MAX_ATTACHMENTS} ondersteunde bijlagen")
    if not attachments:
        raise EmailValidationError("Geen PDF- of STEP-bijlagen gevonden")

    raw_message_id = str(message.get("Message-ID") or "").strip()
    message_id = raw_message_id or f"sha256:{hashlib.sha256(raw).hexdigest()}"
    fingerprint_input = "\n".join(
        [message_id, *sorted(attachment.sha256 for attachment in attachments)]
    ).encode("utf-8")
    fingerprint = hashlib.sha256(fingerprint_input).hexdigest()
    sender = parseaddr(str(message.get("From") or ""))[1]

    return IncomingEmail(
        message_id=message_id,
        sender=sender,
        subject=str(message.get("Subject") or ""),
        received_at=str(message.get("Date") or ""),
        fingerprint=fingerprint,
        attachments=tuple(attachments),
    )


def store_attachments(email: IncomingEmail, target: Path) -> list[StoredAttachment]:
    """Store attachments without trusting sender-controlled paths."""

    target.mkdir(parents=True, exist_ok=False)
    stored: list[StoredAttachment] = []
    used_names: set[str] = set()

    for attachment in email.attachments:
        name = attachment.filename
        if name.casefold() in used_names:
            stem = Path(name).stem
            suffix = Path(name).suffix
            name = f"{stem}-{attachment.sha256[:8]}{suffix}"
        used_names.add(name.casefold())
        destination = target / name
        destination.write_bytes(attachment.payload)
        stored.append(
            StoredAttachment(
                filename=name,
                content_type=attachment.content_type,
                sha256=attachment.sha256,
                path=destination,
            )
        )
    return stored

