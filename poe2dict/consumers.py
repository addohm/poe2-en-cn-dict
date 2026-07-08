"""Consumer-facing exports built from the generated ``dictionary/`` output.

These are thin reshapers: they read the already-produced ``tables/`` and
``lookup/`` files and re-emit them in the exact shape a downstream tool wants.
No datamining happens here, so this module can run standalone against an existing
``dictionary/`` dir (see ``export_consumers.py``) or be appended to a full build.

Currently ships one consumer:

``consumers/trade-helper/`` — the runtime maps the **poe2cn-trade-helper**
userscript injects as ``DICT``. Everything here is client-derived; the trade
helper supplies the trade-API *structural* id -> label maps itself (from a live
CN-only fetch), translating those label strings through ``cn_to_en.json`` below.

Output files (all UTF-8, compact JSON; ``zh`` = Simplified as shipped by WeGame):

  items.json          { zh: en }         base-item display names  (BaseItemTypes)
  item_classes.json   { zh: en }         item-class names         (ItemClasses)
  skills.json         { names:{zh:en}, desc:{zh:en} }  gem/skill  (ActiveSkills)
  uniques.json        { zh: en }         unique / word names      (Words.Text2)
  stat_lines.json     [[zh, en], ...]    mod-line templates, {N} placeholders
  stat_by_hash.json   { hash: {en,zh} }  one #-form template per GGG trade hash
  meta.json           counts + provenance

The flat lookups (cn_to_en/en_to_cn) and the trade_id_to_stat crosswalk are NOT
duplicated here — read them from the sibling ``../../lookup/`` if a consumer needs
them (they are ~10 MB each and unchanged).

Placeholder conventions (must match the userscript, verified against
userscript.template.js):
  * ``stat_lines`` keeps GGG index placeholders as bare ``{0}``/``{1}`` — the
    userscript fills them via ``en.replace(/\\{(\\d+)\\}/g, ...)``.
  * ``stat_by_hash`` uses trade-style ``#`` — the userscript's ``fillNums``
    injects the rolled numbers in order into each ``#``.
"""
import json
import os
import re

# PoE rich-text markup: "[Key|Display]" -> "Display"; "[Display]" -> "Display".
_TAG_PIPE = re.compile(r"\[([^\]|]+)\|([^\]]+)\]")
_TAG_PLAIN = re.compile(r"\[([^\]]+)\]")
# A GGG placeholder with an optional format spec, e.g. {0}, {1}, {0:+d}, {0:d}.
_PH = re.compile(r"\{(\d+)[^}]*\}")


def strip_tags(s):
    if not s:
        return ""
    return _TAG_PLAIN.sub(r"\1", _TAG_PIPE.sub(r"\2", s))


def _to_hash_form(s):
    """{0}/{0:+d}/... -> '#'  (fillNums convention)."""
    return _PH.sub("#", s or "")


def _to_index_form(s):
    """{0:+d} -> {0}  (drop the format spec, keep the index)."""
    return _PH.sub(r"{\1}", s or "")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def _column_pairs(dict_dir, table, column):
    """Yield (zh, en) for one column of one table file, in row order.

    Scalar columns yield one pair; array columns yield each element. Silently
    yields nothing if the table or column is absent (table may not have been
    generated on a given patch)."""
    path = os.path.join(dict_dir, "tables", f"{table}.json")
    if not os.path.exists(path):
        return
    data = _load(path)
    for entry in data.get("entries", []):
        cells = entry.get("columns", {}).get(column)
        if not cells:
            continue
        for cell in cells:
            en, zh = cell.get("en"), cell.get("zh")
            if en and zh:
                yield zh, en


def _zh_to_en_map(dict_dir, table, column):
    """First zh wins on collision (matches the trade helper's setdefault)."""
    out = {}
    for zh, en in _column_pairs(dict_dir, table, column):
        out.setdefault(zh, en)
    return out


def _pick_form(forms):
    """Choose the canonical display form for a stat block. The trade API's
    per-id text is the positive/increased phrasing, so prefer a form whose
    value_range is non-negative; fall back to the first form."""
    for f in forms:
        vr = f.get("value_range") or ""
        if f.get("en") and "-1" not in vr and not vr.startswith("-"):
            return f
    return forms[0] if forms else None


def build_trade_helper(dict_dir, out_dir=None):
    """Reshape ``dict_dir`` (a generated dictionary/) into the trade-helper
    consumer bundle. Returns a counts dict."""
    if out_dir is None:
        out_dir = os.path.join(dict_dir, "consumers", "trade-helper")
    os.makedirs(out_dir, exist_ok=True)
    lookup = os.path.join(dict_dir, "lookup")

    # 1-4: client name maps ----------------------------------------------------
    items = _zh_to_en_map(dict_dir, "BaseItemTypes", "Name")
    item_classes = _zh_to_en_map(dict_dir, "ItemClasses", "Name")
    uniques = _zh_to_en_map(dict_dir, "Words", "Text2")

    skill_names = {}
    for zh, en in _column_pairs(dict_dir, "ActiveSkills", "DisplayedName"):
        if zh != en:
            skill_names.setdefault(zh, en)
    skill_desc = {}
    for zh, en in _column_pairs(dict_dir, "ActiveSkills", "Description"):
        zt, et = strip_tags(zh), strip_tags(en)
        if zt and et and zt != et:
            skill_desc.setdefault(zt, et)

    _dump(items, os.path.join(out_dir, "items.json"))
    _dump(item_classes, os.path.join(out_dir, "item_classes.json"))
    _dump(uniques, os.path.join(out_dir, "uniques.json"))
    _dump({"names": skill_names, "desc": skill_desc},
          os.path.join(out_dir, "skills.json"))

    # 5: stat-line templates ---------------------------------------------------
    blocks = _load(os.path.join(lookup, "stat_lines.json"))
    stat_lines = []            # [[zh, en], ...]  ({N} form)
    stat_by_hash = {}          # hash -> {en, zh}  (# form)
    seen = set()
    for b in blocks:
        for f in b.get("forms", []):
            en, zh = f.get("en"), f.get("zh")
            if not en or not zh:
                continue
            zi, ei = _to_index_form(zh), _to_index_form(en)
            if zi == ei:
                continue
            k = (zi, ei)
            if k in seen:
                continue
            seen.add(k)
            stat_lines.append([zi, ei])
        h = b.get("stat_hash")
        if h and h not in stat_by_hash:
            f = _pick_form(b.get("forms", []))
            if f and f.get("en"):
                stat_by_hash[h] = {
                    "en": _to_hash_form(f["en"]),
                    "zh": _to_hash_form(f["zh"]) if f.get("zh") else None,
                }
    _dump(stat_lines, os.path.join(out_dir, "stat_lines.json"))
    _dump(stat_by_hash, os.path.join(out_dir, "stat_by_hash.json"))

    # NB: the giant flat lookups (cn_to_en/en_to_cn, ~10 MB each) and the
    # trade_id_to_stat crosswalk are intentionally NOT copied here — they already
    # live verbatim in the sibling ``../../lookup/`` and copying them would just
    # duplicate ~20 MB into the repo. A consumer that needs them reads lookup/.

    # 6: meta ------------------------------------------------------------------
    src_meta = {}
    src_meta_path = os.path.join(dict_dir, "meta.json")
    if os.path.exists(src_meta_path):
        src_meta = _load(src_meta_path)
    counts = {
        "items": len(items),
        "item_classes": len(item_classes),
        "uniques": len(uniques),
        "skill_names": len(skill_names),
        "skill_desc": len(skill_desc),
        "stat_lines": len(stat_lines),
        "stat_by_hash": len(stat_by_hash),
    }
    meta = {
        "consumer": "poe2cn-trade-helper",
        "generatedAt": src_meta.get("generatedAt"),
        "schemaVersion": src_meta.get("schemaVersion"),
        "sourceDictionary": os.path.abspath(dict_dir),
        "counts": counts,
    }
    _dump(meta, os.path.join(out_dir, "meta.json"))

    _write_readme(out_dir)
    return counts


def _write_readme(out_dir):
    readme = """# Consumer export: poe2cn-trade-helper

Client-derived runtime maps for the trade-helper userscript's injected `DICT`.
Regenerate with `python export_consumers.py` (or a full `python update.py`).
Everything here comes from the game client; the trade helper supplies the
trade-API structural id -> label maps itself (live CN-only fetch), translating
those label strings through `cn_to_en.json`.

| file | shape | use |
|---|---|---|
| `items.json` | `{zh:en}` | base-item display names |
| `item_classes.json` | `{zh:en}` | item-class names |
| `skills.json` | `{names:{zh:en}, desc:{zh:en}}` | gem/skill names + descriptions (markup-stripped) |
| `uniques.json` | `{zh:en}` | unique / affix word names (Words.Text2) |
| `stat_lines.json` | `[[zh,en],...]` | mod-line templates, GGG `{N}` placeholders |
| `stat_by_hash.json` | `{hash:{en,zh}}` | one trade-style `#` template per GGG trade stat hash |
| `meta.json` | counts + provenance | build report |

The flat lookups (`cn_to_en`/`en_to_cn`) and the `trade_id_to_stat` crosswalk are
**not** duplicated here — read them from the sibling `../../lookup/` (~10 MB each,
unchanged).

## Joining stats by GGG trade id

A trade id like `explicit.stat_2513318031` carries the hash `2513318031`; the
`explicit.`/`implicit.`/`fractured.` prefix is mod-context, not part of the hash.
So: `hash = tid.split("stat_")[-1]` then `stat_by_hash[hash]`. The prefix + the
CN side of each id come from the live CN `/api/trade2/data/stats` response.

## Placeholder conventions (match the userscript exactly)

- `stat_lines` keeps `{0}`/`{1}`… (format specs like `{0:+d}` are reduced to
  `{0}`; the sign rides with the rolled value). Filled via
  `en.replace(/\\{(\\d+)\\}/g, ...)`.
- `stat_by_hash` uses `#`; filled in order by the userscript's `fillNums`.
"""
    with open(os.path.join(out_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)
