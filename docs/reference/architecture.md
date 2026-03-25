# Architecture

This page explains how data moves through the extractor, how configuration is resolved, and how reliability controls work during production batch runs.

## Component map

```mermaid
flowchart TB
    CLI[main.py CLI] --> DETECT[customer_detection.py]
    CLI --> BATCH[Batch/Single Orchestration]
    BATCH --> ROUTER[model_service.py]
    BATCH --> CONFIG[config_loader.py]
    BATCH --> PROMPT[prompt_builder.py]
    ROUTER --> GEMINI[gemini_service.py]
    ROUTER --> OLLAMA[ollama_service.py]
    GEMINI --> TYPES[types.py Pydantic models]
    OLLAMA --> TYPES
    BATCH --> WARN[operator_warnings.py]
    BATCH --> XML[xml_writer.py]
    BATCH --> CSV[csv_logger.py]
    BATCH --> CONST[constants.py]
    BATCH --> UTILS[utils.py]
```

## End-to-end extraction flow

```mermaid
sequenceDiagram
    autonumber
    participant U as User/Operator
    participant CLI as CLI main.py
    participant CD as Customer Detection
    participant CFG as Config Loader
    participant RT as Provider Router
    participant PB as Prompt Builder
    participant GS as Gemini Service
    participant OS as Ollama Service
    participant OW as Operator Warnings
    participant XW as XML Writer
    participant LG as CSV Logger

    U->>CLI: Run pdf-extract <pdf/folder>
    CLI->>CD: Detect customer (if --customer auto)
    CD-->>CLI: customer_id + confidence
    CLI->>RT: Route by --provider
    CLI->>CFG: Load and merge YAML config
    CFG-->>CLI: effective rules
    alt provider=gemini
        CLI->>PB: Build task prompt + signal hints
        PB-->>CLI: final prompt text
        CLI->>GS: Send PDF bytes + function schema
        GS-->>CLI: structured extraction
    else provider=ollama
        CLI->>OS: Select ollama mode (auto/text/vision)
        OS->>OS: text -> extract text from PDF
        OS->>OS: vision -> render PDF pages to PNG
        OS->>OS: call Ollama /api/chat with JSON output
        OS-->>CLI: structured extraction
    end
    CLI->>OW: Generate post-processing warnings
    OW-->>CLI: warning messages
    CLI->>XW: Serialize OrderDetails to XML
    CLI->>LG: Append status/timing per PDF
    XW-->>U: PDF_XML_<folder>.xml
```

## Configuration resolution

```mermaid
flowchart LR
    A[config/base.yaml] --> M[deep_merge]
    B[customers/<id>/config.yaml] --> M
    C[customers/<id>/surface-treatments.yaml] --> O[Inject surfaceTreatments]
    M --> O
    O --> D[Effective CustomerConfig]
```

Notes:

- Customer lists replace base lists (not append), preventing mixed regex behavior.
- `surface-treatments.yaml` is injected after base+customer merge to keep customer coating vocab explicit.

## Provider routing

```mermaid
flowchart LR
    A[CLI options] --> B{provider}
    B -->|gemini| C[gemini_service.py]
    B -->|ollama| D[ollama_service.py]
    C --> E[OrderDetails]
    D --> E[OrderDetails]
```

Notes:

- Gemini path uses native PDF vision + function calling.
- Ollama path supports text and vision mode via local chat API JSON output.
- In Ollama mode, customer auto-detection falls back to `base`.

## Ollama mode pipeline

```mermaid
flowchart LR
    A[provider=ollama] --> B{ollama_mode}
    B -->|auto| C{Model name looks like vision?}
    C -->|yes| D[vision mode]
    C -->|no| E[text mode]
    B -->|vision| D
    B -->|text| E
    D --> F[Render first PDF pages to PNG base64]
    E --> G[Extract text with pypdf]
    F --> H[Ollama /api/chat]
    G --> H
    H --> I[Parse JSON to OrderDetails]
```

## Batch reliability control flow

```mermaid
stateDiagram-v2
    [*] --> Processing

    Processing --> RetryWait: 429/503 or overloaded
    RetryWait --> Processing: exponential backoff + jitter

    Processing --> Success: extraction ok
    Success --> Processing: next PDF

    Processing --> Failure: non-retryable or max retries reached
    Failure --> BreakerCheck

    BreakerCheck --> Pause: failures >= threshold
    Pause --> Processing: resume after cooldown
    BreakerCheck --> Processing: failures below threshold

    Processing --> [*]: all PDFs handled
```

## Assembly two-pass logic

```mermaid
flowchart TD
    A[Initial extraction for all PDFs] --> B[Detect assembly candidate via BOM cross-reference]
    B --> C{Assembly found?}
    C -->|No| F[Write final XML]
    C -->|Yes| D[Re-extract assembly in BOM-only mode]
    D --> E[Merge better BOM/surface treatment fields]
    E --> F[Write final XML]
```
