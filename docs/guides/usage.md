# Usage

## CLI syntax

```bash
pdf-extract <path_to_pdf_or_folder> [options]
```

## Common commands

```bash
# Single PDF with explicit customer
pdf-extract drawing.pdf --customer elten

# Batch with auto-detection
pdf-extract /path/to/order_folder --customer auto

# Select model
pdf-extract /path/to/order_folder --customer auto --model gemini-2.0-flash

# Use Ollama local model
pdf-extract drawing.pdf --provider ollama --model llama3.1:8b --customer base

# Use Ollama vision model
pdf-extract drawing.pdf --provider ollama --model qwen2.5vl:7b --ollama-mode vision --customer base

# Custom output directory
pdf-extract /path/to/order_folder --output ./output

# Explicit XML output path
pdf-extract drawing.pdf --xml ./results/result.xml
```

## Customers

- `auto`: detect from first PDF
- `elten`: ELTEN-specific rules
- `rademaker`: Rademaker-specific rules
- `base`: generic fallback rules

## Models

- `gemini-2.5-pro` (default): best production accuracy
- `gemini-2.0-flash`: faster and cheaper high-volume option
- `gemini-2.0-flash-lite`: budget/testing option

## Providers

- `gemini` (default): native PDF vision flow
- `ollama`: local model flow via Ollama HTTP API

## Ollama modes

- `auto`: detect mode from model name
- `text`: PDF text extraction + local model parsing
- `vision`: render PDF pages to images and send to vision model

### Ollama quick workflow

```bash
ollama serve
ollama pull llama3.1:8b
pdf-extract drawing.pdf --provider ollama --model llama3.1:8b --customer base

# Vision-first workflow
ollama pull qwen2.5vl:7b
pdf-extract drawing.pdf --provider ollama --model qwen2.5vl:7b --ollama-mode vision --customer base
```

If Ollama is hosted elsewhere:

```bash
pdf-extract drawing.pdf --provider ollama --model llama3.1:8b --ollama-url http://host:11434 --customer base
```

### Suggested model matrix (current SOTA landscape)

| Model | Mode | Relative quality | Speed | Best use |
|-------|------|------------------|-------|----------|
| `qwen2.5vl:7b` | vision | High | Fast-Medium | Most local technical drawing runs |
| `qwen2.5vl:32b` | vision | Very High | Slow | Highest local quality |
| `llama3.2-vision:11b` | vision | Medium-High | Medium | Balanced vision option |
| `minicpm-v:8b` | vision | Medium | Fast | Lighter hardware |
| `llama3.1:8b` | text | Medium-Low | Fast | Text-heavy PDFs |

Note: `--customer auto` is only available in Gemini mode.

!!! warning "Retry behavior"
    API retry logic handles transient 429/503 errors, but malformed PDFs still fail immediately.
