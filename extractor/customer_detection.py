"""Customer detection service using Gemini Vision API."""

import base64
import logging

from google import genai
from google.genai import types

from .constants import DEFAULT_GEMINI_MODEL
from .types import CustomerDetectionResult
from .utils import get_api_key

logger = logging.getLogger(__name__)


async def detect_customer_from_pdf_vision(
    pdf_base64: str,
) -> CustomerDetectionResult:
    """
    Detect customer from PDF using Gemini Vision.

    Looks at the BOM table (bottom right) for customer name.

    Args:
        pdf_base64: Base64-encoded PDF content

    Returns:
        CustomerDetectionResult with customer, confidence, and reason
    """
    try:
        api_key = get_api_key()
        client = genai.Client(api_key=api_key)

        prompt = """You are analyzing a technical drawing PDF. Look at the BOM table (Bill of Materials) in the BOTTOM RIGHT corner of the drawing.

TASK: Identify the customer name from the BOM table.

Common customer names to look for:
- "ELTEN" or "Elten"
- "RADEMAKER" or "Rademaker"
- Other company names in the BOM header or title block

IMPORTANT:
- Look specifically in the bottom right area where the BOM table is located
- The customer name is usually in the title block or BOM header
- Return ONLY the customer name, nothing else
- If you see "ELTEN", respond with: ELTEN
- If you see "RADEMAKER", respond with: RADEMAKER
- If you cannot clearly identify a customer name, respond with: UNKNOWN

Your response should be a single word: either the customer name or UNKNOWN."""

        # Create PDF part
        pdf_part = types.Part.from_bytes(
            data=base64.b64decode(pdf_base64),
            mime_type="application/pdf",
        )

        response = await client.aio.models.generate_content(
            model=DEFAULT_GEMINI_MODEL,
            contents=[prompt, pdf_part],
        )
        response_text = response.text.strip().upper()

        # Parse the response
        if "ELTEN" in response_text:
            return CustomerDetectionResult(
                customer="elten",
                confidence="high",
                reason='Detected "ELTEN" in BOM table via Vision API',
            )
        elif "RADEMAKER" in response_text:
            return CustomerDetectionResult(
                customer="rademaker",
                confidence="high",
                reason='Detected "RADEMAKER" in BOM table via Vision API',
            )
        elif "UNKNOWN" in response_text:
            return CustomerDetectionResult(
                customer="base",
                confidence="low",
                reason="No customer name found in BOM table - using base configuration",
            )
        else:
            return CustomerDetectionResult(
                customer="base",
                confidence="medium",
                reason=f'Found customer name "{response_text}" but no specific config - using base configuration',
            )

    except Exception as e:
        logger.warning(f"Vision-based customer detection failed: {e}")
        return CustomerDetectionResult(
            customer="base",
            confidence="low",
            reason=f"Vision API error: {str(e)}",
        )


# Synchronous wrapper
def detect_customer_from_pdf_vision_sync(pdf_base64: str) -> CustomerDetectionResult:
    """Synchronous version of detect_customer_from_pdf_vision."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # Already in async context - create new loop in thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, detect_customer_from_pdf_vision(pdf_base64))
            return future.result()
    else:
        return asyncio.run(detect_customer_from_pdf_vision(pdf_base64))
