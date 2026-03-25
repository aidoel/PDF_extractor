# Build and Distribution

This project can be distributed as a standalone executable using PyInstaller.

## Install build dependencies

```bash
pip install -r requirements-build.txt
```

## Build executable

```bash
python build_executable.py
```

Generated artifacts:

- macOS/Linux: `dist/pdf-extract`
- Windows: `dist/pdf-extract.exe`

## Validate binary

```bash
./dist/pdf-extract --help
```

## Security expectations

!!! note "Source code visibility"
    Shipping an executable makes casual inspection harder than sharing `.py` files, but Python executables are still reverse-engineerable.

If stronger protection is required, use legal controls (license agreements), server-side execution for sensitive logic, or a compiled language boundary for critical IP.
