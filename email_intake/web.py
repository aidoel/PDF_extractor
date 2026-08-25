"""Small tailnet-friendly web UI for the email intake proof of concept."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .service import EmailIntakeService


_JOB_ID = re.compile(r"^[a-f0-9]{16}$")


@dataclass(frozen=True)
class IntakeWebApp:
    """State shared by all HTTP request handlers."""

    service: EmailIntakeService
    sample_email: Path

    def process_sample(self) -> str:
        return self.service.process_eml(self.sample_email).job_id

    def load_job(self, job_id: str) -> dict[str, Any] | None:
        if not _JOB_ID.fullmatch(job_id):
            return None
        path = self.service.runs / job_id / "result.json"
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None

    def recent_jobs(self) -> list[dict[str, Any]]:
        paths = sorted(
            self.service.runs.glob("*/result.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        jobs: list[dict[str, Any]] = []
        for path in paths[:10]:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                jobs.append(value)
        return jobs


class IntakeHttpServer(ThreadingHTTPServer):
    """HTTP server carrying typed application state."""

    def __init__(
        self,
        server_address: tuple[str, int],
        app: IntakeWebApp,
    ) -> None:
        self.app = app
        super().__init__(server_address, IntakeRequestHandler)


class IntakeRequestHandler(BaseHTTPRequestHandler):
    """Serve dashboard, healthcheck and sample-processing action."""

    server: IntakeHttpServer
    server_version = "EmailIntakePOC/1.0"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json({"status": "ok", "mode": "proof-of-concept"})
            return
        if path == "/":
            self._send_html(_dashboard(self.server.app.recent_jobs()))
            return
        if path.startswith("/jobs/"):
            job_id = path.removeprefix("/jobs/")
            job = self.server.app.load_job(job_id)
            if job is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_html(_job_page(job))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlparse(self.path).path
        if path != "/process-sample":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > 0:
            self.rfile.read(content_length)
        try:
            job_id = self.server.app.process_sample()
        except Exception as exc:
            self._send_html(
                _layout(
                    "Verwerking mislukt",
                    '<section class="card error"><h2>Verwerking mislukt</h2>'
                    f"<p>{html.escape(str(exc))}</p></section>",
                ),
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/jobs/{job_id}")
        self.end_headers()

    def _send_html(
        self, body: str, *, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, value: dict[str, str]) -> None:
        payload = json.dumps(value).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def create_server(
    *,
    workspace: Path,
    sample_email: Path,
    host: str = "127.0.0.1",
    port: int = 8780,
) -> IntakeHttpServer:
    """Create the POC server without starting its blocking loop."""

    app = IntakeWebApp(
        service=EmailIntakeService(workspace),
        sample_email=sample_email.resolve(),
    )
    return IntakeHttpServer((host, port), app)


def _dashboard(jobs: list[dict[str, Any]]) -> str:
    rows = ""
    for job in jobs:
        job_id = html.escape(str(job.get("job_id", "")))
        email = job.get("email") if isinstance(job.get("email"), dict) else {}
        subject = html.escape(str(email.get("subject", "")))
        status = html.escape(str(job.get("status", "")))
        rows += (
            "<tr>"
            f'<td><a href="/jobs/{job_id}">{job_id}</a></td>'
            f"<td>{subject}</td><td><span class=\"pill\">{status}</span></td>"
            "</tr>"
        )
    if not rows:
        rows = '<tr><td colspan="3" class="muted">Nog geen jobs</td></tr>'
    content = f"""
    <header>
      <div><p class="eyebrow">E-MAIL → PRODUCTIEDATA</p>
      <h1>Order intake POC</h1>
      <p class="lead">Lokale testmail, PDF/STEP-controle en een veilig alesERP-concept.</p></div>
      <span class="mode">DRAFT ONLY</span>
    </header>
    <section class="card action">
      <div><h2>Voorbeeldorder POC-1001</h2>
      <p>2 stuks · S235JR · 3 mm · poedercoaten zwart</p></div>
      <form method="post" action="/process-sample">
        <button type="submit">Verwerk voorbeeldmail</button>
      </form>
    </section>
    <section class="card">
      <h2>Recente verwerkingen</h2>
      <table><thead><tr><th>Job</th><th>Onderwerp</th><th>Status</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </section>
    <p class="notice">Deze POC schrijft niets naar het echte alesERP.</p>
    """
    return _layout("Order intake POC", content)


def _job_page(job: dict[str, Any]) -> str:
    job_id = html.escape(str(job.get("job_id", "")))
    status = html.escape(str(job.get("status", "")))
    parts = job.get("parts") if isinstance(job.get("parts"), list) else []
    conflicts = job.get("conflicts") if isinstance(job.get("conflicts"), list) else []
    part_cards = ""
    for part in parts:
        if not isinstance(part, dict):
            continue
        values = [
            ("Onderdeel", part.get("part_number")),
            ("Aantal", part.get("quantity")),
            ("Materiaal", part.get("material")),
            ("Dikte", f'{part.get("thickness_mm")} mm'),
            ("Nabehandeling", part.get("surface_treatment")),
        ]
        items = "".join(
            f"<div><dt>{html.escape(label)}</dt><dd>{html.escape(str(value or '-'))}</dd></div>"
            for label, value in values
        )
        part_cards += f'<section class="card"><dl>{items}</dl></section>'
    conflict_html = ""
    if conflicts:
        messages = "".join(
            f"<li>{html.escape(str(item.get('message', 'Conflict')))}</li>"
            for item in conflicts
            if isinstance(item, dict)
        )
        conflict_html = (
            '<section class="card error"><h2>Handmatige controle nodig</h2>'
            f"<ul>{messages}</ul></section>"
        )
    content = f"""
    <a class="back" href="/">← Terug naar overzicht</a>
    <header><div><p class="eyebrow">JOB {job_id}</p><h1>{status}</h1></div>
    <span class="mode">DRAFT ONLY</span></header>
    {conflict_html}{part_cards}
    <section class="card"><h2>Auditresultaat</h2>
      <pre>{html.escape(json.dumps(job, indent=2, ensure_ascii=False))}</pre>
    </section>
    """
    return _layout(f"Job {job_id}", content)


def _layout(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--ink:#15211b;--muted:#66736c;--paper:#f3f0e8;--card:#fffdf8;--accent:#d45b32;--line:#d9d3c7;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,sans-serif}}
main{{width:min(1000px,calc(100% - 32px));margin:0 auto;padding:48px 0 72px}} header{{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:30px}}
h1{{font:700 clamp(2.2rem,7vw,5rem)/.95 Georgia,serif;margin:4px 0 14px;letter-spacing:-.04em}} h2{{margin:0 0 8px;font-size:1.08rem}} p{{margin:0}} .lead{{color:var(--muted);max-width:620px}}
.eyebrow{{font-size:.75rem;font-weight:800;letter-spacing:.16em;color:var(--accent)}} .mode,.pill{{font-size:.72rem;font-weight:800;letter-spacing:.08em;border:1px solid var(--line);border-radius:99px;padding:8px 12px;white-space:nowrap}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;margin:16px 0;box-shadow:0 8px 30px #463b2710}} .action{{display:flex;align-items:center;justify-content:space-between;gap:20px}}
button{{border:0;border-radius:10px;padding:13px 18px;background:var(--accent);color:white;font-weight:750;cursor:pointer}} button:hover{{filter:brightness(.92)}} table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:12px 8px;border-bottom:1px solid var(--line)}} th{{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}}
a{{color:var(--ink);font-weight:700}} .back{{display:inline-block;margin-bottom:28px}} .notice,.muted{{color:var(--muted)}} .notice{{text-align:center;margin-top:26px}} .error{{border-color:#d45b32;background:#fff7f3}}
dl{{margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:18px}} dt{{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}} dd{{margin:4px 0 0;font-weight:750}} pre{{overflow:auto;background:#172019;color:#edf1ea;padding:16px;border-radius:10px;font-size:.78rem}}
@media(max-width:620px){{main{{padding-top:28px}} header,.action{{display:block}} .mode{{display:inline-block;margin-top:18px}} button{{width:100%;margin-top:18px}} th:nth-child(2),td:nth-child(2){{display:none}}}}
</style></head><body><main>{content}</main></body></html>"""

