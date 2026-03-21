#!/usr/bin/env python3
"""
PDF Extractor CLI

Extract manufacturing data from technical drawing PDFs using Gemini AI.

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

from .constants import DEFAULT_GEMINI_MODEL
from .csv_logger import log_pdf_result
from .customer_detection import detect_customer_from_pdf_vision
from .prompt_builder import PROMPT_VERSION
from .gemini_service import extract_order_details_from_pdf, read_pdf_as_base64
from .types import ExtractionOptions, OrderDetails, OrderItem, ProcessingMetadata
from .xml_writer import build_simple_order_xml

# Load environment variables
load_dotenv()

console = Console()


async def process_with_retry(
    pdf_base64: str,
    options: ExtractionOptions,
    max_retries: int = 7,
) -> OrderDetails:
    """
    Process PDF with exponential backoff retry on 503/429 errors.

    Args:
        pdf_base64: Base64-encoded PDF content
        options: Extraction options
        max_retries: Maximum number of retries

    Returns:
        OrderDetails with extracted data
    """
    delays = [2, 4, 8, 16, 30, 60, 60]  # seconds

    for attempt in range(max_retries + 1):
        try:
            result = await extract_order_details_from_pdf(pdf_base64, options)
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
            jitter = random.random()  # 0-1 second random jitter
            total_delay = delay + jitter

            console.print(
                f"[yellow]API error (attempt {attempt + 1}/{max_retries + 1}), "
                f"retrying in {total_delay:.1f}s...[/yellow]"
            )
            await asyncio.sleep(total_delay)

    raise RuntimeError("Max retries exceeded")


async def extract_single_pdf(
    pdf_path: Path,
    customer_id: str = "elten",
    output_dir: Optional[Path] = None,
    xml_path: Optional[Path] = None,
    model: str = DEFAULT_GEMINI_MODEL,
) -> OrderDetails:
    """
    Extract data from a single PDF.

    Args:
        pdf_path: Path to PDF file
        customer_id: Customer ID (elten, rademaker, base)
        output_dir: Optional output directory
        xml_path: Optional explicit XML output path
        model: Gemini model to use

    Returns:
        OrderDetails with extracted data
    """
    if not pdf_path.exists():
        console.print(f"[red]PDF not found: {pdf_path}[/red]")
        sys.exit(1)

    pdf_base64 = read_pdf_as_base64(pdf_path)
    pdf_name = pdf_path.stem

    console.print(f"[blue]Processing PDF: {pdf_name}[/blue]")

    options = ExtractionOptions(
        customer_id=customer_id,
        pdf_filename=pdf_name,
        model=model,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Extracting with Gemini...", total=None)
        data = await process_with_retry(pdf_base64, options)

    # Determine order name from first item's partNumber
    order_name = (
        data.items[0].part_number
        if data.items and data.items[0].part_number
        else pdf_name
    )

    # Determine output paths
    # Format: PDF_XML_<folder_name>.xml (e.g., PDF_XML_20260001.xml)
    folder_name = pdf_path.parent.name
    xml_filename = f"PDF_XML_{folder_name}.xml"
    
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        xml_out = output_dir / xml_filename
    elif xml_path:
        xml_out = xml_path
    else:
        # Default: write XML in the same folder as the input PDF
        xml_out = pdf_path.parent / xml_filename

    # Write XML
    xml_str = build_simple_order_xml(data)
    with open(xml_out, "w", encoding="utf-8") as f:
        f.write(xml_str)
    
    console.print(f"[green]Wrote XML to {xml_out}[/green]")

    return data


def detect_assembly(items: list[OrderItem]) -> Optional[str]:
    """
    Detect assembly drawing from multiple PDFs.
    Assembly = PDF whose BOM references other PDFs in the order.

    Args:
        items: List of extracted items

    Returns:
        Part number of the assembly drawing, or None
    """
    if len(items) == 1:
        return items[0].part_number

    for item in items:
        if not item.bom_part_numbers:
            continue

        # Check if BOM part numbers match other items' part numbers
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


# Circuit breaker state
consecutive_failures = 0
MAX_CONSECUTIVE_FAILURES = 5
CIRCUIT_BREAKER_DELAY = 5 * 60  # 5 minutes
_failure_lock = asyncio.Lock()


async def circuit_breaker_check():
    """Check circuit breaker and pause if needed."""
    global consecutive_failures
    async with _failure_lock:
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            console.print(
                f"\n[red]CIRCUIT BREAKER: {consecutive_failures} consecutive failures[/red]"
            )
            console.print(
                f"[yellow]Pausing for {CIRCUIT_BREAKER_DELAY // 60} minutes to let API recover...[/yellow]\n"
            )
            await asyncio.sleep(CIRCUIT_BREAKER_DELAY)
            consecutive_failures = 0


async def extract_batch(
    pdfs_folder: Path,
    customer_id: str = "auto",
    output_dir: Optional[Path] = None,
    model: str = DEFAULT_GEMINI_MODEL,
) -> OrderDetails:
    """
    Extract data from multiple PDFs in a folder.

    Args:
        pdfs_folder: Folder containing PDF files
        customer_id: Customer ID or "auto" for auto-detection
        output_dir: Optional output directory
        model: Gemini model to use

    Returns:
        Combined OrderDetails
    """
    global consecutive_failures

    if not pdfs_folder.exists():
        console.print(f"[red]Folder not found: {pdfs_folder}[/red]")
        sys.exit(1)

    # Find all PDFs
    pdf_files = sorted(
        [f for f in pdfs_folder.iterdir() if f.suffix.lower() == ".pdf"],
        key=lambda x: x.name,
    )

    if not pdf_files:
        console.print(f"[red]No PDF files found in {pdfs_folder}[/red]")
        sys.exit(1)

    # Determine output directory
    order_name = pdfs_folder.name
    if output_dir is None:
        # Default: write XML in the same folder as the input PDFs
        output_dir = pdfs_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    # Auto-detect customer from first PDF
    if customer_id == "auto":
        console.print("[blue]Auto-detecting customer from first PDF...[/blue]")
        first_pdf_base64 = read_pdf_as_base64(pdf_files[0])
        detection = await detect_customer_from_pdf_vision(first_pdf_base64)
        customer_id = detection.customer
        console.print(
            f"[green]Detected customer: {customer_id.upper()} "
            f"({detection.confidence} confidence)[/green]"
        )
        console.print(f"[dim]Reason: {detection.reason}[/dim]")
    else:
        console.print(f"[blue]Using provided customer: {customer_id}[/blue]")

    console.print(f"\n[blue]Processing {len(pdf_files)} PDFs...[/blue]")

    all_items: list[OrderItem] = []
    failed_items: list[OrderItem] = []
    success_count = 0
    fail_count = 0
    detected_customer_name = customer_id.upper()

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

            # Check circuit breaker
            await circuit_breaker_check()

            # Track time per PDF
            start_time = time.time()
            error_msg = ""

            try:
                options = ExtractionOptions(
                    customer_id=customer_id,
                    pdf_filename=pdf_name,
                    model=model,
                )
                data = await process_with_retry(pdf_base64, options)
                async with _failure_lock:
                    consecutive_failures = 0  # Reset on success

                elapsed_time = time.time() - start_time

                if data.items:
                    all_items.extend(data.items)
                    success_count += 1
                    # Update description to show last success
                    progress.update(task_id, description=f"Processing... (Last: [green]{pdf_name}[/green])")
                    # Log success to CSV
                    log_pdf_result(
                        order_name=pdfs_folder.name,
                        pdf_name=pdf_name,
                        status="SUCCESS",
                        elapsed_time=elapsed_time,
                        error="",
                        customer=detected_customer_name,
                        prompt_version=PROMPT_VERSION,
                    )
                else:
                    fail_count += 1
                    # Add as failed item
                    failed_items.append(OrderItem(part_number=pdf_name, status="FAILED"))
                    progress.update(task_id, description=f"Processing... (Last: [yellow]{pdf_name} - Empty[/yellow])")
                    # Log empty response as failure
                    log_pdf_result(
                        order_name=pdfs_folder.name,
                        pdf_name=pdf_name,
                        status="FAILED",
                        elapsed_time=elapsed_time,
                        error="Empty response",
                        customer=detected_customer_name,
                        prompt_version=PROMPT_VERSION,
                    )

                # Rate limiting: 1 second between PDFs
                if i < len(pdf_files) - 1:
                    await asyncio.sleep(1)

            except Exception as e:
                elapsed_time = time.time() - start_time
                error_msg = str(e)
                async with _failure_lock:
                    consecutive_failures += 1
                fail_count += 1
                # Add as failed item
                failed_items.append(OrderItem(part_number=pdf_name, status="FAILED"))
                console.print(f"[red]Error extracting {pdf_name}: {e}[/red]")
                progress.update(task_id, description=f"Processing... (Last: [red]Error {pdf_name}[/red])")
                # Log failure to CSV
                log_pdf_result(
                    order_name=pdfs_folder.name,
                    pdf_name=pdf_name,
                    status="FAILED",
                    elapsed_time=elapsed_time,
                    error=error_msg,
                    customer=detected_customer_name,
                    prompt_version=PROMPT_VERSION,
                )

            progress.advance(task_id)

    # Create metadata
    metadata = ProcessingMetadata(
        total_pdfs=len(pdf_files),
        successful_pdfs=success_count,
        failed_pdfs=fail_count,
        detected_customer=detected_customer_name,
    )

    # Combine failed items first, then successful items
    combined_items = failed_items + all_items

    # Create combined order with metadata
    combined_order = OrderDetails(items=combined_items, metadata=metadata)

    # Detect assembly (only from successful items)
    assembly_part_number = detect_assembly(all_items)

    # Re-extract assembly in BOM-only mode if detected
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
                    model=model,
                    is_assembly=True,
                )
                assembly_data = await process_with_retry(assembly_base64, assembly_options)

                if assembly_data.items:
                    bom_data = assembly_data.items[0]
                    # Smart merge: only take surface treatment and BOM part numbers from re-extraction
                    # Keep original holes, tolerances, and other data from first extraction
                    updated_items = []
                    for item in combined_order.items:
                        if item.part_number == assembly_part_number:
                            # Check if re-extraction found a better surface treatment
                            new_surface = bom_data.surface_treatment
                            old_surface = item.surface_treatment
                            # Use new surface treatment if original was None/empty
                            if new_surface and new_surface.lower() not in ("none", ""):
                                if not old_surface or old_surface.lower() in ("none", ""):
                                    item.surface_treatment = new_surface
                            # Also take BOM part numbers if found
                            if bom_data.bom_part_numbers:
                                item.bom_part_numbers = bom_data.bom_part_numbers
                        updated_items.append(item)
                    combined_order.items = updated_items
            except Exception as e:
                console.print(
                    f"[yellow]Assembly BOM-only re-extraction failed: {e}[/yellow]"
                )

    # Determine output filename based on input folder name
    # Format: PDF_XML_<folder_name>.xml (e.g., PDF_XML_20260001.xml)
    output_name = f"PDF_XML_{pdfs_folder.name}"

    # Write XML only
    xml_out = output_dir / f"{output_name}.xml"

    xml_str = build_simple_order_xml(combined_order)
    with open(xml_out, "w", encoding="utf-8") as f:
        f.write(xml_str)

    console.print(f"\n[green]Done: {success_count} successful, {fail_count} failed[/green]")
    if assembly_part_number:
        console.print(f"[blue]Detected assembly: {assembly_part_number}[/blue]")
    console.print(f"[green]Output: {xml_out}[/green]\n")

    return combined_order


@click.command()
@click.argument("pdf_path", required=True, type=click.Path(exists=True))
@click.option("--customer", "-c", default="elten", help="Customer ID (elten, rademaker, base, auto)")
@click.option("--output", "-o", type=click.Path(), help="Output directory")
@click.option("--xml", "xml_path", type=click.Path(), help="XML output path")
@click.option("--model", "-m", default=DEFAULT_GEMINI_MODEL, help="Gemini model to use")
def cli(
    pdf_path: str,
    customer: str,
    output: Optional[str],
    xml_path: Optional[str],
    model: str,
):
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
    """
    pdf_path_obj = Path(pdf_path)
    output_dir = Path(output) if output else None

    if pdf_path_obj.is_dir():
        # Batch mode - folder provided
        asyncio.run(
            extract_batch(
                pdfs_folder=pdf_path_obj,
                customer_id=customer,
                output_dir=output_dir,
                model=model,
            )
        )
    else:
        # Single PDF mode
        asyncio.run(
            extract_single_pdf(
                pdf_path=pdf_path_obj,
                customer_id=customer,
                output_dir=output_dir,
                xml_path=Path(xml_path) if xml_path else None,
                model=model,
            )
        )


if __name__ == "__main__":
    cli()
