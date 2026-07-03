"""Build the PoE2 Simplified-Chinese <-> English translation dictionary.

Python port of the reference builder. See README for the methodology; briefly:
  - Both clients share an identical English base at "Data/Balance".
  - Each language is a row-aligned overlay ("Data/Balance/<Language>").
  - Only the CN (WeGame) client ships "Simplified Chinese".
  - A cell is a genuine translation iff it differs between a client's base and
    its overlay. We pair CN base English <-> CN overlay Chinese (same client,
    same row) and use the international client only to validate the English.
"""
import argparse
import datetime
import io
import json
import os
import shutil

from .ooz import Ooz
from .bundle import FileLoader
from .dat import read_dat_file, build_headers, read_string_column

EN_PATH = "Data/Balance"
ZH_PATH = "Data/Balance/Simplified Chinese"
POE2 = 2


def is_text(v):
    return isinstance(v, str) and len(v) > 0


def col_name(col, i):
    return col.get("name") or f"__col{i}"


def pick_key_column(table):
    uniques = [
        (col_name(c, i), c)
        for i, c in enumerate(table["columns"])
        if c.get("type") == "string" and c.get("unique")
    ]
    if not uniques:
        return None
    for name, c in uniques:
        if c.get("name") == "Id":
            return name
    for name, c in uniques:
        if c.get("name") and c["name"].lower().endswith("id"):
            return name
    return uniques[0][0]


def read_table(loader, lang_path, table_name, table_schema, want):
    """Return {row_count, cols:{name:list}} for the wanted string columns, or None."""
    try:
        data = loader.try_get_file(f"{lang_path}/{table_name}.datc64")
    except Exception:
        return None
    if data is None:
        return None
    try:
        datf = read_dat_file(data)
        headers = build_headers(table_schema["columns"])
        by_name = {h["name"]: h for h in headers}
        cols = {}
        for name in want:
            h = by_name.get(name)
            if h is None:
                continue
            cols[name] = read_string_column(h, datf)
        return {"row_count": datf.row_count, "cols": cols}
    except Exception:
        return None


def build(cn_dir, intl_dir, schema_path, out_dir):
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    print(f"Schema version {schema['version']}, {len(schema['tables'])} tables")

    ooz = Ooz()
    cn = FileLoader(cn_dir, ooz)
    intl = FileLoader(intl_dir, ooz)

    # PoE2 tables (deduped by name) with >=1 string column.
    candidates = []
    seen = set()
    for t in schema["tables"]:
        if not (t["validFor"] & POE2):
            continue
        if t["name"] in seen:
            continue
        string_cols = [col_name(c, i) for i, c in enumerate(t["columns"]) if c.get("type") == "string"]
        if not string_cols:
            continue
        seen.add(t["name"])
        candidates.append((t, string_cols))
    print(f"{len(candidates)} PoE2 tables have >=1 string column")

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(os.path.join(out_dir, "tables"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "lookup"), exist_ok=True)

    cn_to_en = {}   # zh -> {en: count}
    en_to_cn = {}   # en -> {zh: count}
    intl_en = set()

    def add_term(m, src, dst):
        inner = m.get(src)
        if inner is None:
            m[src] = inner = {}
        inner[dst] = inner.get(dst, 0) + 1

    stats = dict(candidates=len(candidates), tablesWithOverlay=0, tablesWithOutput=0, entries=0, pairs=0)
    per_table = {}

    pairs_fd = io.open(os.path.join(out_dir, "pairs.ndjson"), "w", encoding="utf-8", newline="\n")

    for t, string_cols in candidates:
        name = t["name"]
        key_name = pick_key_column(t)
        want = list(dict.fromkeys(([key_name] if key_name else []) + string_cols))

        zh = read_table(cn, ZH_PATH, name, t, want)
        if zh is None:
            continue
        stats["tablesWithOverlay"] += 1
        base = read_table(cn, EN_PATH, name, t, want)
        if base is None:
            continue
        intl_base = read_table(intl, EN_PATH, name, t, want)

        data_cols = [c for c in string_cols if c != key_name]

        # Collect international English strings for validation (trimmed).
        if intl_base is not None:
            for c in data_cols:
                col = intl_base["cols"].get(c)
                if not col:
                    continue
                for v in col:
                    if is_text(v):
                        intl_en.add(v.strip())
                    elif isinstance(v, list):
                        for el in v:
                            if is_text(el):
                                intl_en.add(el.strip())

        base_cols = base["cols"]
        zh_cols = zh["cols"]
        key_list = base_cols.get(key_name) if key_name else None
        base_rc = base["row_count"]

        entries = []
        for idx in range(zh["row_count"]):
            if idx >= base_rc:
                break
            k = None
            if key_list is not None and idx < len(key_list) and is_text(key_list[idx]):
                k = key_list[idx]

            cols_out = {}
            for c in data_cols:
                base_col = base_cols.get(c)
                zh_col = zh_cols.get(c)
                if base_col is None or zh_col is None:
                    continue
                base_val = base_col[idx]
                zh_val = zh_col[idx]

                def push_pair(en, zhs):
                    if not is_text(en) or not is_text(zhs):
                        return
                    if en == zhs:
                        return
                    cols_out.setdefault(c, []).append({"en": en, "zh": zhs})
                    ent = en.strip()
                    zht = zhs.strip()
                    if ent and zht and ent != zht:
                        add_term(cn_to_en, zht, ent)
                        add_term(en_to_cn, ent, zht)
                    stats["pairs"] += 1
                    pairs_fd.write(json.dumps(
                        {"table": name, "column": c, "id": k, "index": idx, "en": en, "zh": zhs},
                        ensure_ascii=False) + "\n")

                if isinstance(base_val, list) and isinstance(zh_val, list):
                    if len(base_val) == len(zh_val):
                        for a, b in zip(base_val, zh_val):
                            push_pair(a, b)
                else:
                    push_pair(base_val, zh_val)

            if cols_out:
                entries.append({"id": k, "index": idx, "columns": cols_out})

        if entries:
            with open(os.path.join(out_dir, "tables", f"{name}.json"), "w", encoding="utf-8") as f:
                json.dump({"table": name, "key": key_name or "_index", "columns": data_cols, "entries": entries},
                          f, ensure_ascii=False, indent=2)
            per_table[name] = len(entries)
            stats["entries"] += len(entries)
            stats["tablesWithOutput"] += 1

    pairs_fd.close()

    def collapse(m):
        best, multi = {}, {}
        for src, inner in m.items():
            variants = sorted(inner.items(), key=lambda kv: -kv[1])
            best[src] = variants[0][0]
            if len(variants) > 1:
                multi[src] = [{"target": tgt, "count": cnt} for tgt, cnt in variants]
        return best, multi

    c2e_best, c2e_multi = collapse(cn_to_en)
    e2c_best, e2c_multi = collapse(en_to_cn)

    def dump(obj, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: obj[k] for k in sorted(obj)}, f, ensure_ascii=False, separators=(",", ":"))

    dump(c2e_best, os.path.join(out_dir, "lookup", "cn_to_en.json"))
    dump(e2c_best, os.path.join(out_dir, "lookup", "en_to_cn.json"))
    dump(c2e_multi, os.path.join(out_dir, "lookup", "cn_to_en.multi.json"))
    dump(e2c_multi, os.path.join(out_dir, "lookup", "en_to_cn.multi.json"))

    en_verified = sum(1 for en in e2c_best if en in intl_en)
    en_total = len(e2c_best)

    meta = {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "schemaVersion": schema["version"],
        "sources": {"cn": cn_dir, "intl": intl_dir},
        "languagePaths": {"en": EN_PATH, "zh_Hans": ZH_PATH},
        "stats": {
            **stats,
            "distinctCnTerms": len(c2e_best),
            "distinctEnTerms": en_total,
            "ambiguousCnTerms": len(c2e_multi),
            "ambiguousEnTerms": len(e2c_multi),
            "intlEnStrings": len(intl_en),
            "enTermsVerifiedInIntl": en_verified,
            "enTermsVerifiedPct": round(en_verified / en_total * 100, 2) if en_total else 0,
        },
        "perTableEntryCounts": {k: per_table[k] for k in sorted(per_table)},
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Ship the consumer-facing format docs alongside the output.
    readme_tpl = os.path.join(os.path.dirname(__file__), "vendor", "dictionary_README.md")
    if os.path.exists(readme_tpl):
        shutil.copyfile(readme_tpl, os.path.join(out_dir, "README.md"))

    print("\n==== DONE ====")
    print(json.dumps(meta["stats"], ensure_ascii=False, indent=2))
    return meta


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(here, "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    p = argparse.ArgumentParser(description="Build the PoE2 CN<->EN translation dictionary")
    p.add_argument("--cn", default=cfg.get("cn"))
    p.add_argument("--intl", default=cfg.get("intl"))
    p.add_argument("--schema", default=os.path.join(here, "poe2dict", "vendor", "schema.min.json"))
    p.add_argument("--out", default=os.path.join(here, "dictionary"))
    a = p.parse_args()
    if not a.cn or not a.intl:
        p.error("cn and intl install paths required (via config.json or --cn/--intl)")
    build(a.cn, a.intl, a.schema, a.out)


if __name__ == "__main__":
    main()
