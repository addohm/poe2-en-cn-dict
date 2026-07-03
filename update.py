#!/usr/bin/env python3
"""Refresh the community dat-schema, then rebuild the dictionary.

Run this after either game client is patched:

    python update.py

Options:  --cn <dir>  --intl <dir>  --out <dir>  --skip-schema-download
Install paths default to config.json.
"""
import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from poe2dict.build import build

SCHEMA_PATH = os.path.join(ROOT, "poe2dict", "vendor", "schema.min.json")


def load_config():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def download_schema(url):
    print(f"Downloading latest dat-schema...\n  {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "poe2-en-cn-dict"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    # Validate it parses before overwriting the vendored copy.
    json.loads(data.decode("utf-8"))
    with open(SCHEMA_PATH, "wb") as f:
        f.write(data)
    print(f"  saved {len(data):,} bytes")


def main():
    cfg = load_config()
    p = argparse.ArgumentParser()
    p.add_argument("--cn", default=cfg.get("cn"))
    p.add_argument("--intl", default=cfg.get("intl"))
    p.add_argument("--out", default=os.path.join(ROOT, "dictionary"))
    p.add_argument("--skip-schema-download", action="store_true")
    a = p.parse_args()

    for label, path in (("cn", a.cn), ("intl", a.intl)):
        idx = os.path.join(path, "Bundles2", "_.index.bin")
        if not os.path.exists(idx):
            sys.exit(f"No PoE2 bundle index under '{path}' (check config.json '{label}').")

    if not a.skip_schema_download:
        try:
            download_schema(cfg.get("schemaUrl"))
        except Exception as e:
            if os.path.exists(SCHEMA_PATH):
                print(f"WARNING: schema download failed ({e}); using vendored copy.")
            else:
                sys.exit(f"Schema download failed and no vendored copy exists: {e}")

    build(a.cn, a.intl, SCHEMA_PATH, a.out)
    print(f"\nDictionary written to {a.out}")


if __name__ == "__main__":
    main()
