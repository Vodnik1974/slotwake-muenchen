#!/usr/bin/env python3
"""Backward-compatible alias → scripts/concierge.py """
from pathlib import Path
import runpy
import sys

sys.argv[0] = str(Path(__file__).with_name("concierge.py"))
runpy.run_path(str(Path(__file__).with_name("concierge.py")), run_name="__main__")
