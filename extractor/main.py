#!/usr/bin/env python3
"""
PDF Extractor CLI

Extract manufacturing data from technical drawing PDFs using Gemini or Ollama.

Usage:
    pdf-extract <pdf_file>
    pdf-extract <pdf_file> --customer elten --output results/
    pdf-extract --batch <folder> --customer auto
"""

import asyncio
import random
import sys
import time
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from .constants import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_MODEL_PROVIDER,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODE,
    DEFAULT_OLLAMA_MODEL,
)
from .csv_logger import log_pdf_result
from .customer_detection import detect_customer_from_pdf_vision
from .gemini_service import read_pdf_as_base64
from .model_service import extract_order_details
from .types import ExtractionOptions, OrderDetails, OrderItem, ProcessingMetadata
from .utils import setup_environment
from .xml_writer import build_simple_order_xml

# One-time environment setup (removes GOOGLE_API_KEY conflict warning)
load_dotenv()
setup_environment()

console = Console()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

async def process_with_retry(
    pdf_base64: str,
    options: ExtractionOptions,
    max_retries: int = 7,
) -> OrderDetails:
    """
    Process a PDF with exponential backoff retry on 503/429 errors.

    Args:
        pdf_base64: Base64-encoded PDF content
        options: Extraction options
        max_retries: Maximum number of retry attempts

    Returns:
        OrderDetails with extracted data
    """
    delays = [2, 4, 8, 16, 30, 60, 60]  # seconds between retries

    for attempt in range(max_retries + 1):
        try:
            result = await extract_order_details(pdf_base64, options)
            if attempt > 0:
                console.print(f"[green]Success after {attempt} retry(ies)[/green]")
            return result
        except Exception as e:
            error_msg = str(e)
            is_retryable = "503" in error_msg or "429" in error_msg or "overloaded" in error_msg
            is_last_attempt = attempt == max_retries

            if not is_retryable or is_last_attempt:
                raise

            delay = delays[attempt] if attempt < len(delays) else 60
            total_delay = delay + random.random()  # add 0–1s jitter
            console.print(
                f"[yellow]API error (attempt {attempt + 1}/{max_retries + 1}), "
                f"retrying in {total_delay:.1f}s...[/yellow]"
            )
            await asyncio.sleep(total_delay)

    raise RuntimeError("Max retries exceeded")


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Pauses processing when too many consecutive failures occur,
    giving the API time to recover before continuing.
    """

    def __init__(self, max_failures: int = 5, pause_seconds: int = 300):
        self.max_failures = max_failures
        self.pause_seconds = pause_seconds
        self._failures = 0
        self._lock = asyncio.Lock()

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1

    async def check(self) -> None:
        """Pause if the failure threshold has been reached."""
        should_pause = False
        async with self._lock:
            if self._failures >= self.max_failures:
                console.print(
                    f"\n[red]CIRCUIT BREAKER: {self._failures} consecutive failures[/red]"
                )
                console.print(
                    f"[yellow]Pausing for {self.pause_seconds // 60} minutes "
                    f"to let API recover...[/yellow]\n"
                )
                self._failures = 0
                should_pause = True

        if should_pause:
            await asyncio.sleep(self.pause_seconds)


# ---------------------------------------------------------------------------
# Single PDF extraction
# ---------------------------------------------------------------------------

async def extract_single_pdf(
    pdf_path: Path,
    customer_id: str = "elten",
    output_dir: Optional[Path] = None,
    xml_path: Optional[Path] = None,
    model: str = DEFAULT_GEMINI_MODEL,
    provider: str = DEFAULT_MODEL_PROVIDER,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_mode: str = DEFAULT_OLLAMA_MODE,
) -> OrderDetails:
    """
    Extract data from a single PDF.

    Args:
        pdf_path: Path to the PDF file
        customer_id: Customer ID (elten, rademaker, base)
        output_dir: Optional output directory override
        xml_path: Optional explicit XML output path
        model: Model name for selected provider
        provider: Backend provider (gemini or ollama)
        ollama_base_url: Ollama server URL when provider=ollama
        ollama_mode: Ollama extraction mode (auto, text, vision)

    Returns:
        OrderDetails with extracted data
    """
    if not pdf_path.exists():
        console.print(f"[red]PDF not found: {pdf_path}[/red]")
        sys.exit(1)

    pdf_base64 = read_pdf_as_base64(pdf_path)
    pdf_name = pdf_path.stem

    console.print(f"[blue]Processing PDF: {pdf_name}[/blue]")
    console.print(f"[dim]Provider={provider} | model={model}[/dim]")
    if provider == "ollama":
        console.print(f"[dim]Ollama mode={ollama_mode}[/dim]")

    options = ExtractionOptions(
        customer_id=customer_id,
        pdf_filename=pdf_name,
        provider=provider,
        model=model,
        ollama_base_url=ollama_base_url,
        ollama_mode=ollama_mode,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description=f"Extracting with {provider}...", total=None)
        data = await process_with_retry(pdf_base64, options)

    # Determine output path: PDF_XML_<folder_name>.xml
    folder_name = pdf_path.parent.name
    xml_filename = f"PDF_XML_{folder_name}.xml"

    if xml_path:
        xml_out = xml_path
    elif output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        xml_out = output_dir / xml_filename
    else:
        xml_out = pdf_path.parent / xml_filename

    xml_str = build_simple_order_xml(data)
    xml_out.write_text(xml_str, encoding="utf-8")
    console.print(f"[green]Wrote XML to {xml_out}[/green]")

    return data


# ---------------------------------------------------------------------------
# Assembly detection
# ---------------------------------------------------------------------------

def detect_assembly(items: list[OrderItem]) -> Optional[str]:
    """
    Find the assembly drawing among extracted items.
    An assembly is a PDF whose BOM references other PDFs in the same order.

    Returns:
        Part number of the assembly drawing, or None
    """
    if len(items) == 1:
        return items[0].part_number

    for item in items:
        if not item.bom_part_numbers:
            continue

        matches = [
            bom_part
            for bom_part in item.bom_part_numbers
            if any(
                other.part_number
                and other.part_number != item.part_number
                and (
                    bom_part.replace("_Rev", "").rstrip("0123456789") in other.part_number
                    or other.part_number.replace("_Rev", "").rstrip("0123456789") in bom_part
                )
                for other in items
            )
        ]

        if matches:
            return item.part_number

    return items[0].part_number if items else None


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------

async def extract_batch(
    pdfs_folder: Path,
    customer_id: str = "auto",
    output_dir: Optional[Path] = None,
    model: str = DEFAULT_GEMINI_MODEL,
    provider: str = DEFAULT_MODEL_PROVIDER,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_mode: str = DEFAULT_OLLAMA_MODE,
) -> OrderDetails:
    """
    Extract data from all PDFs in a folder.

    Args:
        pdfs_folder: Folder containing PDF files
        customer_id: Customer ID or "auto" for auto-detection
        output_dir: Optional output directory override
        model: Model name for selected provider
        provider: Backend provider (gemini or ollama)
        ollama_base_url: Ollama server URL when provider=ollama
        ollama_mode: Ollama extraction mode (auto, text, vision)

    Returns:
        Combined OrderDetails for the entire batch
    """
    if not pdfs_folder.exists():
        console.print(f"[red]Folder not found: {pdfs_folder}[/red]")
        sys.exit(1)

    pdf_files = sorted(
        [f for f in pdfs_folder.iterdir() if f.suffix.lower() == ".pdf"],
        key=lambda x: x.name,
    )

    if not pdf_files:
        console.print(f"[red]No PDF files found in {pdfs_folder}[/red]")
        sys.exit(1)

    order_name = pdfs_folder.name
    if output_dir is None:
        output_dir = pdfs_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    # Auto-detect customer from the first PDF (Gemini only)
    if customer_id == "auto" and provider == "gemini":
        console.print("[blue]Auto-detecting customer from first PDF...[/blue]")
        first_pdf_base64 = read_pdf_as_base64(pdf_files[0])
        detection = await detect_customer_from_pdf_vision(first_pdf_base64)
        customer_id = detection.customer
        console.print(
            f"[green]Detected customer: {customer_id.upper()} "
            f"({detection.confidence} confidence)[/green]"
        )
        console.print(f"[dim]Reason: {detection.reason}[/dim]")
    elif customer_id == "auto" and provider == "ollama":
        console.print("[yellow]Auto customer detection is Gemini-only. Falling back to customer='base' for Ollama.[/yellow]")
        customer_id = "base"
        console.print(f"[blue]Using customer: {customer_id}[/blue]")
    else:
        console.print(f"[blue]Using customer: {customer_id}[/blue]")

    console.print(f"\n[blue]Processing {len(pdf_files)} PDFs...[/blue]")
    console.print(f"[dim]Provider={provider} | model={model}[/dim]")
    if provider == "ollama":
        console.print(f"[dim]Ollama mode={ollama_mode}[/dim]")

    all_items: list[OrderItem] = []
    failed_items: list[OrderItem] = []
    success_count = 0
    fail_count = 0
    detected_customer_name = customer_id.upper()
    circuit_breaker = CircuitBreaker()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Processing PDFs...", total=len(pdf_files))

        for i, pdf_file in enumerate(pdf_files):
            pdf_name = pdf_file.stem
            pdf_base64 = read_pdf_as_base64(pdf_file)

            await circuit_breaker.check()

            start_time = time.time()

            try:
                options = ExtractionOptions(
                    customer_id=customer_id,
                    pdf_filename=pdf_name,
                    provider=provider,
                    model=model,
                    ollama_base_url=ollama_base_url,
                    ollama_mode=ollama_mode,
                )
                data = await process_with_retry(pdf_base64, options)
                await circuit_breaker.record_success()

                elapsed = time.time() - start_time

                if data.items:
                    all_items.extend(data.items)
                    success_count += 1
                    progress.update(
                        task_id,
                        description=f"Processing... (Last: [green]{pdf_name}[/green])",
                    )
                    log_pdf_result(
                        order_name=order_name,
                        pdf_name=pdf_name,
                        status="SUCCESS",
                        elapsed_time=elapsed,
                        error="",
                        customer=detected_customer_name,
                    )
                else:
                    fail_count += 1
                    failed_items.append(OrderItem(part_number=pdf_name, status="FAILED"))
                    progress.update(
                        task_id,
                        description=f"Processing... (Last: [yellow]{pdf_name} - Empty[/yellow])",
                    )
                    log_pdf_result(
                        order_name=order_name,
                        pdf_name=pdf_name,
                        status="FAILED",
                        elapsed_time=elapsed,
                        error="Empty response",
                        customer=detected_customer_name,
                    )

                # Rate limiting: 1 second between requests
                if i < len(pdf_files) - 1:
                    await asyncio.sleep(1)

            except Exception as e:
                elapsed = time.time() - start_time
                await circuit_breaker.record_failure()
                fail_count += 1
                failed_items.append(OrderItem(part_number=pdf_name, status="FAILED"))
                console.print(f"[red]Error extracting {pdf_name}: {e}[/red]")
                progress.update(
                    task_id,
                    description=f"Processing... (Last: [red]Error {pdf_name}[/red])",
                )
                log_pdf_result(
                    order_name=order_name,
                    pdf_name=pdf_name,
                    status="FAILED",
                    elapsed_time=elapsed,
                    error=str(e),
                    customer=detected_customer_name,
                )

            progress.advance(task_id)

    # Build combined result with failed items first
    metadata = ProcessingMetadata(
        total_pdfs=len(pdf_files),
        successful_pdfs=success_count,
        failed_pdfs=fail_count,
        detected_customer=detected_customer_name,
    )
    combined_order = OrderDetails(
        items=failed_items + all_items,
        metadata=metadata,
    )

    # Detect and re-extract assembly in BOM-only mode
    assembly_part_number = detect_assembly(all_items)
    if assembly_part_number and len(pdf_files) > 1:
        assembly_pdf = next(
            (f for f in pdf_files if f.stem == assembly_part_number), None
        )
        if assembly_pdf:
            try:
                console.print(
                    f"[blue]Re-extracting assembly (BOM-only): {assembly_pdf.name}[/blue]"
                )
                assembly_base64 = read_pdf_as_base64(assembly_pdf)
                assembly_options = ExtractionOptions(
                    customer_id=customer_id,
                    pdf_filename=assembly_part_number,
                    provider=provider,
                    model=model,
                    ollama_base_url=ollama_base_url,
                    ollama_mode=ollama_mode,
                    is_assembly=True,
                )
                assembly_data = await process_with_retry(assembly_base64, assembly_options)

                if assembly_data.items:
                    bom_data = assembly_data.items[0]
                    updated = []
                    for item in combined_order.items:
                        if item.part_number == assembly_part_number:
                            # Use re-extracted surface treatment if original was missing
                            new_st = bom_data.surface_treatment
                            if new_st and new_st.lower() not in ("none", ""):
                                if not item.surface_treatment or item.surface_treatment.lower() in ("none", ""):
                                    item.surface_treatment = new_st
                            # Use re-extracted BOM part numbers if found
                            if bom_data.bom_part_numbers:
                                item.bom_part_numbers = bom_data.bom_part_numbers
                        updated.append(item)
                    combined_order.items = updated
            except Exception as e:
                console.print(f"[yellow]Assembly re-extraction failed: {e}[/yellow]")

    # Write XML output
    xml_out = output_dir / f"PDF_XML_{pdfs_folder.name}.xml"
    xml_out.write_text(build_simple_order_xml(combined_order), encoding="utf-8")

    console.print(f"\n[green]Done: {success_count} successful, {fail_count} failed[/green]")
    if assembly_part_number:
        console.print(f"[blue]Detected assembly: {assembly_part_number}[/blue]")
    console.print(f"[green]Output: {xml_out}[/green]\n")

    return combined_order


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@click.command()
@click.argument("pdf_path", required=True, type=click.Path(exists=True))
@click.option("--customer", "-c", default="elten", help="Customer ID (elten, rademaker, base, auto)")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option("--xml", "xml_path", type=click.Path(), help="Explicit XML output path")
@click.option(
    "--provider",
    type=click.Choice(["gemini", "ollama"], case_sensitive=False),
    default=DEFAULT_MODEL_PROVIDER,
    show_default=True,
    help="Extraction backend provider",
)
@click.option(
    "--model",
    "-m",
    default=DEFAULT_GEMINI_MODEL,
    show_default=True,
    help="Model name for selected provider (e.g. gemini-2.5-pro or llama3.1:8b)",
)
@click.option(
    "--ollama-url",
    default=DEFAULT_OLLAMA_BASE_URL,
    show_default=True,
    help="Ollama base URL (used when --provider ollama)",
)
@click.option(
    "--ollama-mode",
    type=click.Choice(["auto", "text", "vision"], case_sensitive=False),
    default=DEFAULT_OLLAMA_MODE,
    show_default=True,
    help="Ollama extraction mode: auto selects based on model name",
)
def cli(
    pdf_path: str,
    customer: str,
    output: Optional[str],
    xml_path: Optional[str],
    provider: str,
    model: str,
    ollama_url: str,
    ollama_mode: str,
) -> None:
    """
    Extract manufacturing data from technical drawing PDFs.

    \b
    Single PDF:
        pdf-extract drawing.pdf
        pdf-extract drawing.pdf --customer elten

    \b
    Batch mode (folder with PDFs):
        pdf-extract /path/to/pdfs/
        pdf-extract /path/to/pdfs/ --customer auto

    \b
    Ollama mode:
        pdf-extract drawing.pdf --provider ollama --model qwen2.5vl:7b --ollama-mode vision --customer base
    """
    path = Path(pdf_path)
    out = Path(output) if output else None

    provider = provider.lower()
    if provider == "ollama" and model == DEFAULT_GEMINI_MODEL:
        model = DEFAULT_OLLAMA_MODEL
    ollama_mode = ollama_mode.lower()

    if path.is_dir():
        asyncio.run(
            extract_batch(
                pdfs_folder=path,
                customer_id=customer,
                output_dir=out,
                provider=provider,
                model=model,
                ollama_base_url=ollama_url,
                ollama_mode=ollama_mode,
            )
        )
    else:
        asyncio.run(
            extract_single_pdf(
                pdf_path=path,
                customer_id=customer,
                output_dir=out,
                xml_path=Path(xml_path) if xml_path else None,
                provider=provider,
                model=model,
                ollama_base_url=ollama_url,
                ollama_mode=ollama_mode,
            )
        )


if __name__ == "__main__":
    cli()
