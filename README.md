# PDF Extractor (Python)

Extract manufacturing data from technical drawing PDFs using Gemini AI.

## E-mailintake proof of concept

De repository bevat ook een volledig lokale proefopstelling voor een toekomstige
mailbox- en alesERP-koppeling. De POC leest een `.eml`-bestand, bewaart PDF- en
STEP-bijlagen veilig, vergelijkt onderdeelnummer/materiaal/dikte en schrijft bij
een foutloze match een `DRAFT_ONLY` alesERP-concept als JSON. De meegeleverde
adapters lezen bewust testmetadata; er wordt nog geen echte mailbox, STEP-engine,
Gemini-service of ERP aangeroepen.

```powershell
python -m email_intake process examples/test-order.eml --workspace poc-data
```

Een lokale inboxmap kan eenmalig of herhaald worden gescand:

```powershell
python -m email_intake watch examples --workspace poc-data --once
```

Start de lokale webinterface (bedoeld om via Tailscale Serve te publiceren):

```powershell
python -m email_intake web --port 8780 --workspace poc-data
```

De SQLite-jobledger voorkomt dat dezelfde mail en bijlagen tweemaal een concept
aanmaken. Verschillen tussen PDF en STEP krijgen status `NEEDS_REVIEW` en leveren
geen ERP-concept op.

## Installatie

### Windows (Aanbevolen - Automatisch)

1. Download de code van GitHub (als ZIP of via git clone)
2. Open PowerShell in de map waar de code staat
3. Voer uit:
   ```powershell
   .\install.ps1
   ```
4. Het script doet automatisch:
   - Virtual environment aanmaken
   - Alle packages installeren
   - Installatie verifiëren
   - `.env` bestand aanmaken (vraagt om API key)

### Windows (Handmatig)

```powershell
# Virtual environment aanmaken
python -m venv venv

# Activeren
.\venv\Scripts\Activate.ps1

# Packages installeren
pip install -r requirements.txt

# Verifieer dat alles werkt
python -c "import click; import google.genai; print('OK!')"
```

### macOS / Linux

```bash
# Virtual environment aanmaken
python -m venv venv
source venv/bin/activate

# Packages installeren
pip install -r requirements.txt

# (Optioneel) Installeer als CLI tool
pip install -e .
```

## Setup

Maak een `.env` bestand aan met je Gemini API key:

```
GEMINI_API_KEY=your_api_key_here
```

**Let op:** Gebruik `GEMINI_API_KEY`, niet `GOOGLE_API_KEY`.

## Usage

### Single PDF

```bash
# Basic usage (auto-detects output location)
pdf-extract drawing.pdf

# Specify customer
pdf-extract drawing.pdf --customer elten

# Custom output
pdf-extract drawing.pdf --output results/
pdf-extract drawing.pdf --json output.json --xml output.xml

# Use different model
pdf-extract drawing.pdf --model gemini-2.5-pro
```

### Batch Processing

```bash
# Process all PDFs in a folder (auto-detect customer)
pdf-extract --batch /path/to/pdfs

# Or use the batch subcommand
pdf-extract batch /path/to/pdfs

# Specify customer
pdf-extract batch /path/to/pdfs --customer rademaker

# Auto-detect customer from first PDF
pdf-extract batch /path/to/pdfs --customer auto

# Custom output directory
pdf-extract batch /path/to/pdfs --output results/
```

## Available Models

- `gemini-2.5-flash` (default, fastest)
- `gemini-2.5-pro` (more accurate)
- `gemini-1.5-flash`
- `gemini-1.5-pro`

## Supported Customers

- `elten` - ELTEN drawings with surface treatments (Parelstralen, Poedercoaten, Verzinken)
- `rademaker` - Rademaker drawings
- `base` - Generic extraction rules
- `auto` - Auto-detect customer from BOM table (batch mode only)

## Output

- **XML**: Formatted output with operator warnings for tap holes, toleranced holes, critical dimensions

Output format: `PDF_XML_<foldername>.xml`

Default output location:
- Single PDF: Same folder as the input PDF
- Batch: Same folder as the input PDFs

## Project Structure

```
python_version/
├── extractor/
│   ├── __init__.py
│   ├── main.py              # CLI entry point
│   ├── types.py             # Pydantic models
│   ├── config_loader.py     # YAML config management
│   ├── gemini_service.py    # Gemini API integration
│   ├── prompt_builder.py    # Prompt generation
│   ├── customer_detection.py # Vision-based detection
│   ├── operator_warnings.py  # Warning generation
│   └── xml_writer.py        # XML output
├── config/
│   ├── base.yaml            # Base configuration
│   └── customers/
│       ├── elten/
│       │   ├── config.yaml
│       │   └── surface-treatments.yaml
│       └── rademaker/
│           ├── config.yaml
│           └── surface-treatments.yaml
├── requirements.txt
├── setup.py
└── README.md
```

## Features

- **Direct CLI**: `pdf-extract` command without npm/server
- **Auto customer detection**: Vision-based detection from BOM table
- **Retry logic**: Exponential backoff on API errors (503, 429)
- **Circuit breaker**: Pause after 5 consecutive failures
- **Assembly detection**: Identifies assembly drawings in batch mode
- **Rich output**: Progress spinners and colored console output

## Example

```bash
# Analyze a batch of technical drawings
$ pdf-extract /path/to/order_123/ --customer auto

Auto-detecting customer from first PDF...
Detected customer: ELTEN (high confidence)
Processing 5 PDFs...
Done: 5 successful, 0 failed
Output: /path/to/order_123/PDF_XML_order_123.xml
```
