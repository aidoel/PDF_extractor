# Getting Started

## Requirements

- Python 3.10+
- A valid `GEMINI_API_KEY`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate  # Windows

pip install -r requirements.txt
pip install -e .
```

Create a `.env` file in the repository root:

```env
GEMINI_API_KEY=your_api_key_here
```

## First run

=== "Single PDF"

    ```bash
    pdf-extract drawing.pdf --customer elten
    ```

=== "Batch Folder"

    ```bash
    pdf-extract /path/to/order_folder --customer auto
    ```

=== "Ollama Local"

    ```bash
    ollama serve
    ollama pull llama3.1:8b
    pdf-extract drawing.pdf --provider ollama --model llama3.1:8b --customer base
    ```

Output is written as `PDF_XML_<foldername>.xml` in the input directory (unless `--output` or `--xml` is used).

!!! tip "Recommended start"
    Use `--customer auto` for production folders unless you know the source customer in advance.
