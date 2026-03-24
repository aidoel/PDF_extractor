# PDF Technical Drawing Extractor

Extract structured manufacturing data from technical drawing PDFs using Google Gemini AI.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
pip install -e .
```

Create a `.env` file:

```
GEMINI_API_KEY=your_api_key_here
```

## Usage

### Single PDF

```bash
pdf-extract drawing.pdf
pdf-extract drawing.pdf --customer elten
pdf-extract drawing.pdf --model gemini-2.5-pro
```

### Batch (folder of PDFs)

```bash
pdf-extract /path/to/order_folder/ --customer auto
pdf-extract /path/to/order_folder/ --customer elten
pdf-extract /path/to/order_folder/ --customer auto --model gemini-2.5-pro
```

**Output:** `PDF_XML_<foldername>.xml` written to the input directory.

## Models

| Model | Cost/PDF | Default |
|-------|----------|---------|
| `gemini-2.5-pro` | ~€0.07 | Yes — 100% accuracy on benchmark |
| `gemini-2.0-flash` | ~€0.025 | — good balance, high volume |
| `gemini-2.0-flash-lite` | ~€0.010 | — budget/testing only |

## Customers

| Value | Description |
|-------|-------------|
| `auto` | Auto-detect from BOM table (recommended for production) |
| `elten` | ELTEN drawings |
| `rademaker` | Rademaker drawings |
| `base` | Generic rules only |

## Output format

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Order>
  <Metadata>
    <TotalPDFs>20</TotalPDFs>
    <SuccessfulPDFs>18</SuccessfulPDFs>
    <FailedPDFs>2</FailedPDFs>
    <DetectedCustomer>ELTEN</DetectedCustomer>
  </Metadata>
  <Items>
    <Item>
      <PartNumber>MD-22-08803</PartNumber>
      <Material>S235 8 mm</Material>
      <SurfaceTreatment>Poedercoaten</SurfaceTreatment>
      <Holes>
        <Hole count="4" type="tapped" threadSize="M6"/>
        <Hole count="2" type="normal" diameter="20" tolerance="H9"/>
      </Holes>
      <ToleratedLengths>
        <ToleratedLength>
          <Dimension>250</Dimension>
          <Upper>+0.5</Upper>
          <Lower>-0.5</Lower>
        </ToleratedLength>
      </ToleratedLengths>
      <PDF_Warnings>
        <Message>Post-processing: 4x M6 tapped, 2x O20 H9, 250 ±0.5</Message>
      </PDF_Warnings>
    </Item>
  </Items>
</Order>
```

See [CLAUDE.md](CLAUDE.md) for full technical documentation.
