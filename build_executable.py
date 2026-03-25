#!/usr/bin/env python3
"""Build a standalone executable with PyInstaller.

Usage:
    python build_executable.py
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_FILE = ROOT / "pdf-extract.spec"


def build_command() -> list[str]:
    separator = ";" if os.name == "nt" else ":"
    add_data = f"config{separator}config"
    entry_script = str(ROOT / "run_pdf_extract.py")

    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "pdf-extract",
        "--onefile",
        "--add-data",
        add_data,
        entry_script,
    ]


def clean_previous_artifacts() -> None:
    for path in (DIST_DIR, BUILD_DIR, SPEC_FILE):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def main() -> int:
    print(f"Building on {platform.system()} {platform.release()}...")
    clean_previous_artifacts()

    command = build_command()
    print("Running:", " ".join(command))
    result = subprocess.run(command, cwd=ROOT, check=False)

    if result.returncode != 0:
        print("Build failed.")
        return result.returncode

    executable = DIST_DIR / ("pdf-extract.exe" if os.name == "nt" else "pdf-extract")
    if executable.exists():
        print(f"Build successful: {executable}")
        return 0

    print("Build finished, but executable was not found in dist/.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
