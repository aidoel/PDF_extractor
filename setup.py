from setuptools import setup, find_packages

setup(
    name="pdf-extractor",
    version="1.0.0",
    description="Extract manufacturing data from technical drawing PDFs using Gemini AI",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "google-genai>=1.0.0",
        "pyyaml>=6.0",
        "python-dotenv>=1.0.0",
        "pydantic>=2.0.0",
        "rich>=13.0.0",
        "click>=8.0.0",
        "pypdf>=4.0.0",
        "pymupdf>=1.24.0",
    ],
    entry_points={
        "console_scripts": [
            "pdf-extract=extractor.main:cli",
        ],
    },
)
