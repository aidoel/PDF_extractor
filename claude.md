# PDF Technical Drawing Extractor

A production Python CLI that extracts structured manufacturing data from technical drawing PDFs using Google Gemini AI. Built for metal fabrication workflows at ALES — processing customer orders from ELTEN and Rademaker.

## What it does

Each technical drawing PDF contains a BOM table, tolerance annotations, hole specifications, and material info. This tool extracts all of it into structured XML, ready for downstream production planning.

**Extracted fields per drawing:**
- Part number
- Surface treatment (coating, galvanizing, powder coat)
- Holes (tapped/reamed/toleranced, with count and thread size)
- Toleranced dimensions (lengths only, with upper/lower bounds)
- Material + thickness
- BOM part numbers (for assembly detection)
- Operator warnings (auto-generated: "Post-processing: 4x M6 tapped, 2x Ø20 H9")

---

## Model Choice

Gemini is the right model for this use case for one specific reason: **native PDF vision**.

Unlike other frontier models that require image conversion, Gemini accepts raw PDF bytes and processes the document as a visual artifact. This is critical for technical drawings:

- **No OCR pipeline** — OCR on technical drawings is lossy. Dimension lines, tolerance symbols (Ø, ±, H7), and multi-cell BOM tables break most OCR systems. Gemini reads layout and meaning directly.
- **Spatial reasoning** — Gemini understands that `Ø20 H9` next to a circle on a drawing means a toleranced hole, not a text string. It parses drawing geometry in context.
- **Table understanding** — The BOM in the bottom-right corner is a visual table. Gemini reads rows, columns, and cell content without needing any preprocessing.

**Gemini 2.5 Pro** is the production default. It uses **thinking tokens** — internal chain-of-thought reasoning billed separately but not visible in the output. This is what makes it significantly more accurate on ambiguous drawings (e.g., overlapping dimensions, non-standard notations). Benchmarked at **100% accuracy** on 1067 real drawings across 70 production orders.

---

## Model Catalogue

| Model | Cost/PDF | Speed | Accuracy | Notes |
|-------|----------|-------|----------|-------|
| `gemini-2.5-pro` ← **default** | €0.07 | 22.8s | **100%** benchmarked | Thinking model. Best for production. |
| `gemini-2.0-flash` | €0.025* | ~18s | ~99%* | Good balance. High-volume option. |
| `gemini-2.0-flash-lite` | €0.010* | ~14s | ~96%* | Budget/testing only. Higher hallucination rate. |
| `gemini-1.5-pro` | €0.080* | ~28s | ~99%* | Older pro. No advantage over 2.5-pro. |
| `gemini-1.5-flash` | €0.020* | ~20s | ~98%* | Older flash. Prefer 2.0-flash. |
| `gemini-1.5-flash-8b` | €0.008* | ~12s | ~94%* | Smallest. Simple drawings only. |

`*` = estimated from Google pricing

Override via CLI: `--model gemini-2.0-flash`
Default set in `extractor/constants.py`.

---

## AI / LLM Design

### Function Calling (`mode=ANY`)

Extraction uses **forced function calling**, not free-text or structured JSON output. `mode="ANY"` forces the model to always call `extract_manufacturing_data` — the schema is treated as a contract, not a formatting hint. The model cannot return anything outside this contract.

### Prompt Engineering

The extraction prompt is **dynamically constructed per request** — not a static template. It composes:

1. **Priority-ordered task list** — Surface treatment is listed first because it's the highest-stakes field (missing coating = scrapped parts). The model sees this ordering as implicit priority.
2. **Customer-specific signal patterns** — Regex patterns from YAML config are injected as concrete examples: `"±\d+" → toleratedLengths`. This reduces hallucination by anchoring the model to expected formats.
3. **Negative examples** — Explicit "DO NOT" instructions: diameter tolerances go in holes, not toleratedLengths; plain numbers without tolerance symbols are ignored; BOM values are not dimensions.
4. **Customer-specific rules** — ELTEN-specific instructions like "scan EVERY cell in the BOM for coating keywords" are injected as a separate block when the ELTEN config is loaded.
5. **OCR signal hints** (optional) — When text signals are pre-extracted, they are injected as `### Detected Text Cues` with a clear disclaimer: "for REFERENCE ONLY — always verify in the PDF image."

Assembly drawings get a separate, focused prompt: extract BOM and surface treatment only, ignore holes and dimensions.

### Two-Pass Assembly Processing

After batch extraction, the system detects which PDF is the assembly drawing by cross-referencing BOM part numbers across all extracted items. The assembly is then **re-extracted in BOM-only mode** — a focused second pass that's more accurate for assembly-level fields (coating, BOM list) than the general extraction prompt.

---

## Architecture

```
extractor/
├── main.py               # CLI (Click), batch/single orchestration
├── gemini_service.py     # Gemini API: singleton client, function calling, response parsing
├── prompt_builder.py     # Dynamic prompt construction
├── config_loader.py      # YAML config loading + deep merge
├── customer_detection.py # Vision-based customer auto-detection (first PDF)
├── operator_warnings.py  # Post-processing: generate human-readable warnings
├── xml_writer.py         # XML serialization
├── csv_logger.py         # Append-only daily CSV log
├── types.py              # Pydantic models (OrderDetails, OrderItem, etc.)
├── constants.py          # Model catalogue + DEFAULT_GEMINI_MODEL
└── utils.py              # get_api_key(), setup_environment()

config/
├── base.yaml                          # Base rules (always loaded)
└── customers/
    ├── elten/
    │   ├── config.yaml                # ELTEN overrides + prompt additions
    │   └── surface-treatments.yaml   # ELTEN coating options
    └── rademaker/
        ├── config.yaml
        └── surface-treatments.yaml
```

### Config System

Config is hierarchical and deep-merged at runtime:

```
base.yaml
    ↓ deep_merge()
customers/<id>/config.yaml
    +
customers/<id>/surface-treatments.yaml
```

Lists are **replaced** (not appended) in the merge — a customer's hole patterns fully override the base, not extend it. This prevents base patterns from conflicting with customer-specific regexes.

Each YAML config controls:
- `signals.tolerated_lengths` — regex patterns with descriptions injected into the prompt
- `signals.holes` — hole detection recipes (pattern → type + metadata)
- `surfaceTreatments` — valid options with keywords for the model to match
- `material_patterns` — natural-language instructions for the material field
- `prompt_additions` — extra rules injected per-field (surface treatment, holes, material)

Adding a new customer = one new YAML file. No code changes.

---

## Production Reliability

### Retry with Exponential Backoff

7 retries on 503/429 errors with delays `[2, 4, 8, 16, 30, 60, 60]` + random jitter (0–1s). Non-retryable errors (malformed PDF, schema mismatch) fail immediately.

### Circuit Breaker

After 5 consecutive failures, the batch pauses for 5 minutes to let the API recover. Implemented as an `asyncio.Lock`-based class instantiated inside the batch function (avoids the DeprecationWarning for Locks created at import time in Python 3.10+).

### Singleton Client

`genai.Client` is created once on first use and reused across all requests. Avoids creating a new HTTP connection per PDF.

### Daily CSV Log

Every PDF result is appended to `logs/pdf_extractor_log_YYYY-MM-DD.csv` with timestamp, order, PDF name, status, elapsed time, error message, and detected customer. Designed for post-run analysis and model improvement tracking.

---

## Quick Start

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

# .env with GEMINI_API_KEY=<key>

# Single PDF
pdf-extract drawing.pdf --customer elten

# Batch (auto-detect customer)
pdf-extract /path/to/order_folder/ --customer auto

# Different model
pdf-extract /path/to/order_folder/ --customer auto --model gemini-2.0-flash
```

**Output:** `PDF_XML_<foldername>.xml` written to the input directory.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `google-genai>=1.0.0` | Gemini API (new SDK — replaces deprecated `google-generativeai`) |
| `pydantic>=2.0.0` | Data validation + serialization with camelCase aliases |
| `pyyaml>=6.0` | YAML config loading |
| `click>=8.0.0` | CLI framework |
| `rich>=13.0.0` | Progress bars + colored terminal output |
| `python-dotenv>=1.0.0` | `.env` loading |
