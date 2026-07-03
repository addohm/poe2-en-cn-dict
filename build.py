#!/usr/bin/env python3
"""Build the dictionary from the currently-vendored schema (offline).

Usage:  python build.py [--cn <dir>] [--intl <dir>] [--out <dir>]
For a fresh schema + build after a game patch, use  python update.py  instead.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from poe2dict.build import main

if __name__ == "__main__":
    main()
