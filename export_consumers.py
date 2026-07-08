#!/usr/bin/env python3
"""Reshape an already-built ``dictionary/`` into consumer-facing exports.

Runs standalone (no datamining, no game client needed) against the committed
``dictionary/`` output. A full ``python build.py`` / ``python update.py`` also
produces these automatically as a final additive step.

Usage:  python export_consumers.py [--dict <dictionary dir>]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from poe2dict.consumers import build_trade_helper


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    p = argparse.ArgumentParser(description="Build consumer-facing dictionary exports")
    p.add_argument("--dict", default=os.path.join(here, "dictionary"),
                   help="path to a generated dictionary/ dir")
    a = p.parse_args()
    if not os.path.isdir(os.path.join(a.dict, "tables")):
        p.error(f"no generated dictionary at {a.dict} (run build.py first)")
    counts = build_trade_helper(a.dict)
    print("==== consumer export: trade-helper ====")
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
