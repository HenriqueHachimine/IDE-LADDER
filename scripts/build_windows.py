#!/usr/bin/env python3
"""Mantido por compatibilidade: use scripts/build_app.py (Windows e Linux)."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.argv[0] = str(Path(__file__).with_name("build_app.py"))
    runpy.run_path(sys.argv[0], run_name="__main__")
