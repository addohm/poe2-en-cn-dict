#!/usr/bin/env python3
"""Ad-hoc dictionary lookups. Direction is auto-detected per term.

    python query.py Dexterity "Chaos Orb" 闪避 敏捷
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
LOOKUP = os.path.join(ROOT, "dictionary", "lookup")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HAN = re.compile(r"[㐀-鿿豈-﫿]")


def load(fn):
    with open(os.path.join(LOOKUP, fn), encoding="utf-8") as f:
        return json.load(f)


def main():
    terms = sys.argv[1:]
    if not terms:
        print(__doc__)
        return
    e2c, c2e = load("en_to_cn.json"), load("cn_to_en.json")
    e2cM, c2eM = load("en_to_cn.multi.json"), load("cn_to_en.multi.json")
    for t in terms:
        if HAN.search(t):
            best, multi = c2e.get(t), c2eM.get(t)
        else:
            best, multi = e2c.get(t), e2cM.get(t)
        line = f"{t}  =>  {best if best is not None else '(not found)'}"
        if multi:
            line += "   [variants: " + ", ".join(f"{v['target']}×{v['count']}" for v in multi) + "]"
        print(line)


if __name__ == "__main__":
    main()
