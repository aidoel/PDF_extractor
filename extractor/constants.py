"""Global constants for the extractor application."""

DEFAULT_MODEL_PROVIDER = "gemini"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODE = "auto"

# ---------------------------------------------------------------------------
# Gemini Model Selection
# ---------------------------------------------------------------------------

DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"

# Alle ondersteunde modellen met metadata
# Gebruik als referentie; het --model argument accepteert elke geldige Gemini model-ID
GEMINI_MODELS: dict[str, dict] = {
    "gemini-2.5-pro": {
        "cost_eur_per_pdf": 0.07,
        "benchmarked": True,
        "notes": "Beste kwaliteit, 100% accuraat op benchmark. Thinking model.",
    },
    "gemini-2.0-flash": {
        "cost_eur_per_pdf": 0.025,
        "benchmarked": False,
        "notes": "Snel en goedkoop. Goede keuze voor hoog volume.",
    },
    "gemini-2.0-flash-lite": {
        "cost_eur_per_pdf": 0.010,
        "benchmarked": False,
        "notes": "Goedkoopste optie. Meer kans op hallucinaties bij complexe tekeningen.",
    },
    "gemini-1.5-pro": {
        "cost_eur_per_pdf": 0.080,
        "benchmarked": False,
        "notes": "Ouder pro-model. Duurder dan 2.5-pro zonder voordeel.",
    },
    "gemini-1.5-flash": {
        "cost_eur_per_pdf": 0.020,
        "benchmarked": False,
        "notes": "Ouder flash-model. Stabiel maar 2.0-flash heeft de voorkeur.",
    },
    "gemini-1.5-flash-8b": {
        "cost_eur_per_pdf": 0.008,
        "benchmarked": False,
        "notes": "Kleinste model. Alleen geschikt voor simpele tekeningen.",
    },
}
