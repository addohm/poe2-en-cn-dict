"""Parse GGG stat-description (.csd) files and emit a stat-line lookup.

These UTF-16 text files hold the display TEMPLATES for every mod line in the
game (including non-tradeable map/monster/socketable/rune lines). Each
`description` block maps one or more internal stat KEYS to conditional display
templates, with the localized text embedded as `lang "<Name>"` sub-sections.

We read the CN (WeGame) client so the Simplified Chinese is exactly what that
client ships (never derived from Traditional Chinese). English is the block's
default (no-lang) section from the same file, so EN/ZH stay perfectly aligned.

Output (added, never replacing existing files):
  lookup/stat_lines.json        array of description blocks (stat_ids, forms, options)
  lookup/trade_id_to_stat.json  { "<hash>": <index into stat_lines> } crosswalk

The number in a GGG trade id ("explicit.stat_2513318031") is a murmur2 hash of
the block's stat key(s); we compute it so consumers join by exact id, not text.
"""
import json
import os
import re
import struct

from .dat import read_dat_file, build_headers, read_string_column

ROOT_DIR = "data/statdescriptions"
SC_LANG = "Simplified Chinese"
EN_LANG = "English"
EN_PATH = "Data/Balance"
ZH_PATH = "Data/Balance/Simplified Chinese"

_BRACKET = re.compile(r"\[([^\[\]]*)\]")
_PLACEHOLDER = re.compile(r"\{[^}]*\}")


def to_hashmark(s):
    """Normalise GGG {0}/{0:+d} placeholders to the trade-style '#' marker."""
    return _PLACEHOLDER.sub("#", s)


# --- trade-id hash (murmur2 with GGG's two salts) ---
def _murmur2(data: bytes, seed: int) -> int:
    m = 0x5BD1E995
    r = 24
    length = len(data)
    h = (seed ^ length) & 0xFFFFFFFF
    i = 0
    while length >= 4:
        k = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24)
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        i += 4
        length -= 4
    if length == 3:
        h ^= data[i + 2] << 16
    if length >= 2:
        h ^= data[i + 1] << 8
    if length >= 1:
        h ^= data[i]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h & 0xFFFFFFFF


def trade_hash(keys) -> int:
    per = b"".join(struct.pack("<I", _murmur2(k.encode("utf-8"), 0xC58F1A7B)) for k in keys)
    return _murmur2(per, 0x02312233)


# --- template text rendering ---
def render_template(text: str) -> str:
    """Resolve GGG [ref|display] link markup to its display form, keep {0}
    placeholders, leading '+' and '%' intact, and turn literal \\n into real
    newlines."""
    while True:
        m = _BRACKET.search(text)
        if not m:
            break
        inner = m.group(1)
        disp = inner.split("|")[-1]  # [Attack|Attacks] -> Attacks ; [Glory] -> Glory
        text = text[: m.start()] + disp + text[m.end():]
    return text.replace("\\n", "\n").strip()


def _parse_matcher(line: str):
    """`<value_range> "<template>" <flags>` -> (value_range, rendered_template)."""
    q = line.find('"')
    if q == -1:
        return None
    pre = line[:q].strip()
    rest = line[q + 1:]
    end = rest.find('"')
    if end == -1:
        return None
    template = render_template(rest[:end])
    return pre, template


def parse_csd(text: str):
    """Yield {stat_ids, sections:{langName:[(value_range, template), ...]}}."""
    stripped = [l.strip() for l in text.splitlines()]
    idxs = [i for i, l in enumerate(stripped) if l == "description"]
    for n, start in enumerate(idxs):
        end = idxs[n + 1] if n + 1 < len(idxs) else len(stripped)
        body = [stripped[i] for i in range(start + 1, end) if stripped[i]]
        if len(body) < 2:
            continue
        ids = body[0].split()
        try:
            count = int(ids[0])
        except ValueError:
            continue
        keys = ids[1 : 1 + count]
        if not keys:
            continue
        sections = {}
        cur = EN_LANG
        for line in body[1:]:
            if line.startswith("lang "):
                try:
                    cur = line.split('"')[1]
                except IndexError:
                    cur = line[5:].strip()
                continue
            if '"' not in line:
                continue  # section count line or noise
            if line.startswith("no_description") or line.startswith("include"):
                continue
            m = _parse_matcher(line)
            if m is not None:
                sections.setdefault(cur, []).append(m)
        if sections:
            yield {"stat_ids": keys, "sections": sections}


def _pair_forms(en_matchers, zh_matchers):
    """Pair English and Simplified-Chinese matcher lines into forms."""
    forms = []
    if en_matchers and zh_matchers and len(en_matchers) == len(zh_matchers):
        pairs = zip(en_matchers, zh_matchers)
        for (rng, en), (_zrng, zh) in pairs:
            forms.append((rng, en, zh))
    else:
        zh_by_range = {}
        for rng, zh in (zh_matchers or []):
            zh_by_range.setdefault(rng, zh)
        for rng, en in en_matchers:
            forms.append((rng, en, zh_by_range.get(rng)))
    return forms


def _detect_options(forms):
    """Inline enum: >=2 forms, each gated by a single exact integer and with no
    numeric placeholder -> a label list (e.g. radius Small/Medium/Large)."""
    if len(forms) < 2:
        return None
    opts = []
    for rng, en, zh in forms:
        if not re.fullmatch(r"-?\d+", rng or ""):
            return None
        if "{" in en or (zh and "{" in zh):
            return None
        opts.append({"en": en, "zh": zh})
    return opts


def _read_two_cols(cn_loader, table_schema, col):
    """Return list of (en, zh) for `col` of a table, aligned by row within the
    CN client (base = English, overlay = Simplified Chinese)."""
    base = cn_loader.try_get_file(f"{EN_PATH}/{table_schema['name']}.datc64")
    over = cn_loader.try_get_file(f"{ZH_PATH}/{table_schema['name']}.datc64")
    if base is None or over is None:
        return []
    bd = read_dat_file(base)
    od = read_dat_file(over)
    headers = build_headers(table_schema["columns"])
    hdr = next((h for h in headers if h["name"] == col), None)
    if hdr is None:
        return []
    b = read_string_column(hdr, bd)
    o = read_string_column(hdr, od)
    n = min(len(b), len(o))
    return [(b[i], o[i]) for i in range(n)]


def extract_wrappers(cn_loader, schema):
    """Find the compound-mod wrapper templates in ClientStrings, e.g.
    "Notable Passive Skills in Radius also grant {0}" and the "Bonded:" rune
    prefix, returning [{en, zh}] with a {0} inner-stat slot."""
    ts = next((t for t in schema["tables"]
               if t["name"] == "ClientStrings" and (t["validFor"] & 2)), None)
    if ts is None:
        return []
    wrappers = []
    seen = set()
    for en_raw, zh_raw in _read_two_cols(cn_loader, ts, "Text"):
        if not en_raw or not zh_raw:
            continue
        en = render_template(en_raw)
        zh = render_template(zh_raw)
        w = None
        if "also grant {0}" in en and "{0}" in zh:
            w = {"en": en, "zh": zh}
        elif en.strip() == "Bonded:" and zh.strip():
            # rune prefix: "Bonded: <inner>"
            w = {"en": en.strip() + " {0}", "zh": zh.strip() + " {0}"}
        if w and w["en"] not in seen:
            seen.add(w["en"])
            wrappers.append(w)
    return wrappers


def build_stat_lines(cn_loader, out_dir, schema=None):
    """Parse every .csd in the CN client and write the stat-line lookups.
    Returns summary stats."""
    csd_paths = sorted(f for f in cn_loader.iter_files(ROOT_DIR) if f.endswith(".csd"))

    by_hash = {}   # hash -> entry dict
    order = []     # preserve first-seen order
    files_parsed = 0
    for path in csd_paths:
        data = cn_loader.try_get_file(path)
        if data is None:
            continue
        files_parsed += 1
        text = data.decode("utf-16", errors="replace")
        for block in parse_csd(text):
            keys = block["stat_ids"]
            sections = block["sections"]
            en = sections.get(EN_LANG)
            if not en:
                continue
            zh = sections.get(SC_LANG)
            forms_raw = _pair_forms(en, zh)
            forms = [
                {"en": en_t, "zh": zh_t, "value_range": rng}
                for (rng, en_t, zh_t) in forms_raw
                if en_t
            ]
            if not forms:
                continue
            h = trade_hash(keys)
            entry = by_hash.get(h)
            if entry is None:
                entry = {"stat_ids": keys, "stat_hash": str(h), "forms": []}
                by_hash[h] = entry
                order.append(h)
            # merge forms, de-duplicating on (en, zh, value_range)
            seen = {(f["en"], f["zh"], f["value_range"]) for f in entry["forms"]}
            for f in forms:
                key = (f["en"], f["zh"], f["value_range"])
                if key not in seen:
                    entry["forms"].append(f)
                    seen.add(key)

    # finalize: add options where the block is an inline enum
    stat_lines = []
    for h in order:
        entry = by_hash[h]
        opts = _detect_options([(f["value_range"], f["en"], f["zh"]) for f in entry["forms"]])
        if opts:
            entry["options"] = opts
        stat_lines.append(entry)

    trade_id_to_stat = {entry["stat_hash"]: i for i, entry in enumerate(stat_lines)}

    # --- English-keyed fallback (trade-style '#'): give me the SC for this
    # English mod line. Covers direct forms plus composed compound mods
    # (rune "Bonded: X" and jewel "... Passive Skills in Radius also grant X"),
    # whose trade hashes GGG generates and are absent from the game files. ---
    by_english = {}
    def add_english(en, zh):
        if not en or not zh:
            return
        k = to_hashmark(en)
        if k not in by_english:
            by_english[k] = to_hashmark(zh)

    for e in stat_lines:
        for fo in e["forms"]:
            add_english(fo["en"], fo["zh"])

    wrappers = extract_wrappers(cn_loader, schema) if schema else []
    composed = 0
    for w in wrappers:
        en_w, zh_w = w["en"], w["zh"]
        for e in stat_lines:
            for fo in e["forms"]:
                # only wrap numeric mod lines (those with a value placeholder);
                # pure labels / flavour text are never granted this way
                if fo["zh"] and "{" in fo["en"]:
                    add_english(en_w.replace("{0}", fo["en"]),
                                zh_w.replace("{0}", fo["zh"]))
                    composed += 1

    lookup_dir = os.path.join(out_dir, "lookup")
    os.makedirs(lookup_dir, exist_ok=True)
    with open(os.path.join(lookup_dir, "stat_lines.json"), "w", encoding="utf-8") as f:
        json.dump(stat_lines, f, ensure_ascii=False, indent=1)
    with open(os.path.join(lookup_dir, "trade_id_to_stat.json"), "w", encoding="utf-8") as f:
        json.dump(trade_id_to_stat, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(lookup_dir, "stat_line_wrappers.json"), "w", encoding="utf-8") as f:
        json.dump(wrappers, f, ensure_ascii=False, indent=1)
    with open(os.path.join(lookup_dir, "stat_line_by_english.json"), "w", encoding="utf-8") as f:
        json.dump({k: by_english[k] for k in sorted(by_english)}, f, ensure_ascii=False, separators=(",", ":"))

    total_forms = sum(len(e["forms"]) for e in stat_lines)
    zh_forms = sum(1 for e in stat_lines for fo in e["forms"] if fo["zh"])
    return {
        "csd_files_parsed": files_parsed,
        "stat_descriptions": len(stat_lines),
        "total_forms": total_forms,
        "forms_with_zh": zh_forms,
        "with_options": sum(1 for e in stat_lines if "options" in e),
        "wrappers": len(wrappers),
        "english_keys": len(by_english),
        "composed_english_keys": composed,
    }
