"""CSV logger for daily PDF extraction logs."""

import csv
from datetime import datetime
from pathlib import Path


def get_log_file_path() -> Path:
    """Get the path for today's log file."""
    today = datetime.now().strftime("%Y-%m-%d")
    # Log file in logs/ directory relative to the extractor package
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir / f"pdf_extractor_log_{today}.csv"


def log_pdf_result(
    order_name: str,
    pdf_name: str,
    status: str,
    elapsed_time: float,
    error: str,
    customer: str,
    prompt_version: str = "",
) -> None:
    """
    Log a single PDF extraction result to the daily CSV log.

    Args:
        order_name: Name of the order/folder being processed
        pdf_name: Name of the PDF file (without extension)
        status: "SUCCESS" or "FAILED"
        elapsed_time: Time taken to process the PDF in seconds
        error: Error message if failed, empty string if successful
        customer: Detected customer name
        prompt_version: Version identifier of the prompt used
    """
    log_file = get_log_file_path()
    file_exists = log_file.exists()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Write header if file is new
        if not file_exists:
            writer.writerow(["Timestamp", "Order", "PDF", "Status", "Time(s)", "Error", "Customer", "PromptVersion"])

        # Write the log entry
        writer.writerow([
            timestamp,
            order_name,
            pdf_name,
            status,
            f"{elapsed_time:.1f}",
            error,
            customer,
            prompt_version,
        ])
