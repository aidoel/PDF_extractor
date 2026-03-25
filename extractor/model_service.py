"""Provider router for extraction backends."""

from typing import Optional

from .gemini_service import extract_order_details_from_pdf
from .ollama_service import extract_order_details_from_pdf_ollama
from .types import ExtractionOptions, OrderDetails


async def extract_order_details(
    pdf_base64: str,
    options: Optional[ExtractionOptions] = None,
) -> OrderDetails:
    """Extract order details using the configured provider."""
    if options is None:
        options = ExtractionOptions()

    provider = (options.provider or "gemini").lower()

    if provider == "gemini":
        return await extract_order_details_from_pdf(pdf_base64, options)

    if provider == "ollama":
        return await extract_order_details_from_pdf_ollama(pdf_base64, options)

    raise ValueError(f"Unsupported provider: {provider}. Use 'gemini' or 'ollama'.")
