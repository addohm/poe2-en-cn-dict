# Task: expand the trade-helper consumer export

**Repo:** this one (`poe2-en-cn-dict`). **Consumer:** the `poe2cn-trade-helper`
userscript, which translates the 国服 trade site to English by consuming
`dictionary/consumers/trade-helper/` (produced by `poe2dict/consumers.py` /
`export_consumers.py`). Design rule from the maintainer: **the dictionary is the
single source of all translation data — the userscript must hold rendering logic
only, never hardcoded translation strings.** So anything the userscript needs to
translate must be exposed here, from the already-datamined tables. No new
datamine is needed — all data below already exists in `dictionary/tables/` and
`dictionary/lookup/`.

## Why

Live testing of the trade site (logged in, userscript active) found these still
untranslated. Each was traced to data that EXISTS in this repo but is NOT in the
consumer export, so the userscript can't reach it:

| Untranslated on site | Example | Lives in |
|---|---|---|
| Magic item affix words (prefix/suffix on rare/magic items) | `狩猎者的` → Hunter's, `凸缘的`, `窑炉之` | `tables/Mods.json` (Name), also `lookup/cn_to_en.json` |
| Gem tags | `辅助`→Support, `攻击`→Attack, `近战`→Melee, `火焰`→Fire | `tables/GemTags.json`, `lookup/cn_to_en.json` |
| Trade-site UI chrome | `加载更多`→Load More, `注销`→Log Out, `类型`→Type, `正在展示…结果`, tooltips, footer | `tables/ClientStrings*.json`, `lookup/cn_to_en.json` |
| Stat-filter group labels | `综合`→Pseudo, `外延`→Explicit, `状态组`, `加权求和`→Weighted Sum | ClientStrings / trade-synthesized |

(Item base types, unique names, and mod-line stat templates are ALREADY exported
and verified 100% covered — do not touch those.)

## What to add to `poe2dict/consumers.py` → `dictionary/consumers/trade-helper/`

Emit these NEW files (same compact-JSON, `{zh: en}` convention as the existing
`items.json`; first zh wins on collision; skip pairs where zh == en):

1. **`affixes.json`** — magic/rare affix display words. Source: `tables/Mods.json`
   Name column (the localized prefix/suffix words like `狩猎者的`→`Hunter's`).
   Include every Mods row that has a non-empty translated Name. These are what the
   userscript will use to translate the words around a base type in an item's
   `typeLine` (e.g. `狩猎者的 Amethyst Ring` → `Hunter's Amethyst Ring`).

2. **`gem_tags.json`** — `tables/GemTags.json` (zh→en). Small.

3. **`ui_terms.json`** — a curated CN→EN map of SHORT UI strings the trade site
   shows as chrome/labels: buttons, tooltips, property labels, flag words, and
   stat-filter group headers. Build it from `tables/ClientStrings.json` +
   `ClientStrings2.json` (and any obviously-UI table), **filtered to short entries**
   (e.g. ≤ 24 chars, no `\n`, no printf/`{}` placeholders) so it stays small and
   collision-safe — this is replacing the userscript's hand-maintained CHROME map,
   not shipping the full 87k-entry `cn_to_en`. Must include at least: `加载更多`,
   `注销`, `用户协议`, `回到主页`, `使用协议及隐私提醒`, `类型`, `综合`, `外延`,
   `状态组`, `加权求和`, `熔炉天赋树路径`, and the toolbar tooltips `清理过滤器组`,
   `默认`, `紧凑`, `双栏紧凑`, `刷新`, `复制物品`, `按物品属性筛选`, `最大品质`.
   If some of these aren't in ClientStrings, fall back to their `cn_to_en.json`
   value (most are present there).

Update the export's `README.md` + `meta.json` counts, and the module docstring.
Keep it all additive — do not change `items/uniques/skills/stat_lines/stat_by_hash`.

## Also check (dictionary correctness)

- The trade `data/stats` has ~27 entries with no English anywhere (mostly
  `配置 <skill>` = "Configure <skill>" pseudo-filters, plus `格挡时威吓敌人 # 秒`).
  These are likely trade-backend-synthesized and may legitimately have no client
  string. If ClientStrings/Mods DO contain them, add them to `stat_by_hash` or a
  small `synthetic_stats.json`; otherwise note them as un-translatable in the
  export README so the consumer can hardcode the handful if needed.
- No wrong (mistranslated) entries were found in this pass; if the consumer later
  reports any, fix them at the source table + regenerate.

## Verify

`python export_consumers.py`, then confirm: `affixes.json` has thousands of
entries incl. `狩猎者的`→`Hunter's`; `gem_tags.json` incl. `辅助`→`Support`;
`ui_terms.json` incl. `加载更多`→`Load More` and stays well under ~1 MB. Commit +
push. The consumer (`poe2cn-trade-helper/tool/build_dict.py`) will then load these
and the userscript will translate the affix/gem/chrome layers.
