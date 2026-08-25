"""Command line interface for the local email intake proof of concept."""

from __future__ import annotations

import time
from pathlib import Path

import click

from .service import EmailIntakeService


@click.group()
def cli() -> None:
    """Process test emails containing PDF and STEP attachments."""


@cli.command("process")
@click.argument("eml_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--workspace",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("poc-data"),
    show_default=True,
)
def process_command(eml_path: Path, workspace: Path) -> None:
    """Process one .eml file and create a mock alesERP draft."""

    result = EmailIntakeService(workspace).process_eml(eml_path)
    duplicate = " (duplicaat, niet opnieuw verwerkt)" if result.duplicate else ""
    click.echo(f"Job: {result.job_id}{duplicate}")
    click.echo(f"Status: {result.status}")
    click.echo(f"Resultaat: {result.result_path}")
    if result.erp_draft_path:
        click.echo(f"Mock alesERP-concept: {result.erp_draft_path}")


@cli.command("watch")
@click.argument("inbox", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--workspace",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("poc-data"),
    show_default=True,
)
@click.option("--interval", type=click.FloatRange(min=0.1), default=2.0, show_default=True)
@click.option("--once", is_flag=True, help="Scan één keer en stop.")
def watch_command(inbox: Path, workspace: Path, interval: float, once: bool) -> None:
    """Watch a local folder that represents the future mailbox connector."""

    service = EmailIntakeService(workspace)
    while True:
        for eml_path in sorted(inbox.glob("*.eml")):
            try:
                result = service.process_eml(eml_path)
                state = "duplicaat" if result.duplicate else result.status
                click.echo(f"{eml_path.name}: {state} ({result.job_id})")
            except Exception as exc:  # POC watcher must continue with the next mail.
                click.echo(f"{eml_path.name}: ERROR: {exc}", err=True)
        if once:
            return
        time.sleep(interval)


@cli.command("web")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", type=click.IntRange(min=1, max=65535), default=8780, show_default=True)
@click.option(
    "--workspace",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("poc-data"),
    show_default=True,
)
@click.option(
    "--sample",
    "sample_email",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("examples/test-order.eml"),
    show_default=True,
)
def web_command(host: str, port: int, workspace: Path, sample_email: Path) -> None:
    """Run the local POC dashboard for a Tailscale Serve proxy."""

    from .web import create_server

    server = create_server(
        workspace=workspace,
        sample_email=sample_email,
        host=host,
        port=port,
    )
    click.echo(f"Order intake POC luistert op http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
