# Consumer export: poe2cn-trade-helper

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
  `en.replace(/\{(\d+)\}/g, ...)`.
- `stat_by_hash` uses `#`; filled in order by the userscript's `fillNums`.
