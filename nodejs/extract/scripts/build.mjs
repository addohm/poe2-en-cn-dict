// Build the PoE2 Simplified-Chinese <-> English translation dictionary.
//
// Strategy (validated empirically):
//  - Both clients share an identical English base at "Data/Balance".
//  - Each language is an overlay folder ("Data/Balance/<Language>") whose rows
//    are 1:1 row-aligned with that same client's base.
//  - The CN (WeGame) client ships the "Simplified Chinese" overlay; the Steam
//    international client does not. So Chinese must come from the CN client.
//  - Clients can be on slightly different patches (different row counts), so
//    cross-client joins use the language-independent `Id` column, never index.
//
// A cell is a genuine translation iff it differs between a client's base file
// and its overlay file (paths / ids / tags are byte-identical and so are
// skipped automatically). We diff CN base vs CN overlay (same client, exact row
// alignment) to decide what is translated, and prefer the international
// client's English wording (joined by Id) as the canonical English, falling
// back to the CN base English when an Id is absent internationally.
//
// We read EVERY string column (named or not) rather than only the schema's
// `localized`-flagged ones, so coverage is not limited by schema annotations.
//
// Outputs (under --out):
//    meta.json                     run metadata + counts
//    tables/<Table>.json           per-table 1:1 entries with full context
//    lookup/cn_to_en.json          term-level Chinese -> English (best guess)
//    lookup/en_to_cn.json          term-level English -> Chinese (best guess)
//    lookup/cn_to_en.multi.json    Chinese -> [English variants w/ counts]
//    lookup/en_to_cn.multi.json    English -> [Chinese variants w/ counts]
//    pairs.ndjson                  every pair with {table,column,id,en,zh}
import { loadClient, loadSchema, readTable, ValidFor } from "./datlib.mjs";
import { buildStatLines } from "./statlines.mjs";
import * as fs from "fs/promises";
import * as path from "path";

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const CN = arg("cn", "C:\\WeGameApps\\rail_apps\\Path of  Exile 2(2002052)");
const INTL = arg("intl", "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Path of Exile 2");
const OUT = arg("out", path.resolve(process.cwd(), "..", "dictionary"));
const SCHEMA = arg("schema", path.join(process.cwd(), "cache", "schema.min.json"));

const EN_PATH = "Data/Balance";
const ZH_PATH = "Data/Balance/Simplified Chinese";
const log = (...a) => console.log(...a);

const isText = (v) => typeof v === "string" && v.length > 0;

function colName(col, i) {
  return col.name || `__col${i}`;
}

function pickKeyColumn(tableSchema) {
  const uniques = tableSchema.columns
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => c.type === "string" && c.unique);
  const byName = uniques.find(({ c }) => c.name === "Id");
  const idish = uniques.find(({ c }) => c.name && /id$/i.test(c.name));
  const chosen = byName ?? idish ?? uniques[0];
  return chosen ? colName(chosen.c, chosen.i) : null;
}

async function tryRead(loader, langPath, name, ts, want) {
  try {
    return await readTable(loader, langPath, name, ts, want);
  } catch {
    return null;
  }
}

async function main() {
  const schema = await loadSchema(SCHEMA);
  log(`Schema version ${schema.version}, ${schema.tables.length} tables`);

  const cn = await loadClient(CN);
  const intl = await loadClient(INTL);

  // PoE2 tables (deduped by name) that have at least one string column.
  const candidates = [];
  const seen = new Set();
  for (const t of schema.tables) {
    if (!(t.validFor & ValidFor.PoE2)) continue;
    if (seen.has(t.name)) continue;
    const stringCols = t.columns
      .map((c, i) => ({ name: colName(c, i), array: c.array, localized: c.localized }))
      .filter((_, i) => t.columns[i].type === "string");
    if (stringCols.length === 0) continue;
    seen.add(t.name);
    candidates.push({ t, stringCols });
  }
  log(`${candidates.length} PoE2 tables have >=1 string column`);

  await fs.rm(OUT, { recursive: true, force: true });
  await fs.mkdir(path.join(OUT, "tables"), { recursive: true });
  await fs.mkdir(path.join(OUT, "lookup"), { recursive: true });
  const pairsFd = await fs.open(path.join(OUT, "pairs.ndjson"), "w");

  const cnToEn = new Map();
  const enToCn = new Map();
  const intlEnSet = new Set(); // all English strings seen in the international client
  function addTerm(map, src, dst) {
    let inner = map.get(src);
    if (!inner) map.set(src, (inner = new Map()));
    inner.set(dst, (inner.get(dst) ?? 0) + 1);
  }

  const stats = {
    candidates: candidates.length,
    tablesWithOverlay: 0,
    tablesWithOutput: 0,
    entries: 0,
    pairs: 0,
  };
  const perTableCounts = {};

  for (const { t, stringCols } of candidates) {
    const name = t.name;
    const keyName = pickKeyColumn(t);
    const want = [...new Set([...(keyName ? [keyName] : []), ...stringCols.map((c) => c.name)])];

    const zh = await tryRead(cn, ZH_PATH, name, t, want);
    if (!zh) continue; // no Simplified Chinese overlay for this table
    stats.tablesWithOverlay++;

    const cnBase = await tryRead(cn, EN_PATH, name, t, want);
    if (!cnBase) continue; // need same-client base to detect diffs
    const intlBase = await tryRead(intl, EN_PATH, name, t, want);

    const keyOf = (row) => (keyName && isText(row[keyName]) ? row[keyName] : null);

    const dataCols = stringCols.map((c) => c.name).filter((n) => n !== keyName);

    // Collect the international client's English strings (for this table) into a
    // global set, used purely to validate that our English is genuine global
    // English. We do NOT join the international client per-row: it has no
    // Simplified Chinese, and its row Ids can drift vs the CN client's patch.
    if (intlBase) for (const r of intlBase.rows) {
      for (const c of dataCols) {
        const v = r[c];
        if (isText(v)) intlEnSet.add(v.trim());
        else if (Array.isArray(v)) for (const el of v) if (isText(el)) intlEnSet.add(el.trim());
      }
    }
    const entries = [];

    for (const zrow of zh.rows) {
      const brow = cnBase.rows[zrow._index]; // exact within-CN alignment
      if (!brow) continue;
      const k = keyOf(brow);

      const cols = {};
      // The English side is ALWAYS the CN client's own base English for that
      // exact row, so it corresponds 1:1 to the CN Chinese in the overlay.
      const pushPair = (en, zhs) => {
        if (!isText(en) || !isText(zhs)) return;
        if (en === zhs) return; // not translated (identical in overlay)
        // Raw values keep full fidelity in per-table + pairs.ndjson outputs.
        (cols[curCol] ??= []).push({ en, zh: zhs });
        // Flat lookups use outer-trimmed keys so they are clean to query.
        const enT = en.trim();
        const zhT = zhs.trim();
        if (enT && zhT && enT !== zhT) {
          addTerm(cnToEn, zhT, enT);
          addTerm(enToCn, enT, zhT);
        }
        stats.pairs++;
        pairsFd.write(
          JSON.stringify({ table: name, column: curCol, id: k ?? null, index: zrow._index, en, zh: zhs }) + "\n"
        );
      };
      let curCol;
      for (const c of dataCols) {
        curCol = c;
        const baseVal = brow[c];
        const zhVal = zrow[c];
        if (Array.isArray(baseVal) && Array.isArray(zhVal)) {
          if (baseVal.length === zhVal.length)
            for (let i = 0; i < baseVal.length; i++) pushPair(baseVal[i], zhVal[i]);
        } else {
          pushPair(baseVal, zhVal);
        }
      }
      if (Object.keys(cols).length > 0) entries.push({ id: k ?? null, index: zrow._index, columns: cols });
    }

    if (entries.length > 0) {
      await fs.writeFile(
        path.join(OUT, "tables", `${name}.json`),
        JSON.stringify({ table: name, key: keyName ?? "_index", columns: dataCols, entries }, null, 2)
      );
      perTableCounts[name] = entries.length;
      stats.entries += entries.length;
      stats.tablesWithOutput++;
    }
  }

  await pairsFd.close();

  function collapse(map) {
    const best = {};
    const multi = {};
    for (const [src, inner] of map) {
      const variants = [...inner.entries()].sort((a, b) => b[1] - a[1]);
      best[src] = variants[0][0];
      if (variants.length > 1) multi[src] = variants.map(([target, count]) => ({ target, count }));
    }
    return { best, multi };
  }
  const c2e = collapse(cnToEn);
  const e2c = collapse(enToCn);
  const sortObj = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));

  // Validation: how many of the dictionary's English terms are verbatim present
  // in the international client (confirms the English side is genuine global
  // English, not a CN-only artifact).
  let enVerified = 0;
  for (const en of Object.keys(e2c.best)) if (intlEnSet.has(en)) enVerified++;
  const enTotal = Object.keys(e2c.best).length;

  await fs.writeFile(path.join(OUT, "lookup", "cn_to_en.json"), JSON.stringify(sortObj(c2e.best)));
  await fs.writeFile(path.join(OUT, "lookup", "en_to_cn.json"), JSON.stringify(sortObj(e2c.best)));
  await fs.writeFile(path.join(OUT, "lookup", "cn_to_en.multi.json"), JSON.stringify(sortObj(c2e.multi)));
  await fs.writeFile(path.join(OUT, "lookup", "en_to_cn.multi.json"), JSON.stringify(sortObj(e2c.multi)));

  const meta = {
    generatedAt: new Date().toISOString(),
    schemaVersion: schema.version,
    sources: { cn: CN, intl: INTL },
    languagePaths: { en: EN_PATH, zh_Hans: ZH_PATH },
    stats: {
      ...stats,
      distinctCnTerms: Object.keys(c2e.best).length,
      distinctEnTerms: enTotal,
      ambiguousCnTerms: Object.keys(c2e.multi).length,
      ambiguousEnTerms: Object.keys(e2c.multi).length,
      intlEnStrings: intlEnSet.size,
      enTermsVerifiedInIntl: enVerified,
      enTermsVerifiedPct: enTotal ? +((enVerified / enTotal) * 100).toFixed(2) : 0,
    },
    perTableEntryCounts: sortObj(perTableCounts),
  };
  await fs.writeFile(path.join(OUT, "meta.json"), JSON.stringify(meta, null, 2));

  // Ship the consumer-facing format docs alongside the output.
  try {
    await fs.copyFile(
      path.join(process.cwd(), "dictionary_README.md"),
      path.join(OUT, "README.md")
    );
  } catch { /* template optional */ }

  log("\n==== DONE (translation dictionary) ====");
  log(JSON.stringify(meta.stats, null, 2));

  // Additive: mod-line templates from the stat-description files. Writes only
  // NEW files under lookup/ and never touches the outputs above.
  log("\n==== stat-description lines ====");
  const sl = await buildStatLines(CN, cn, schema, OUT);
  log(JSON.stringify(sl, null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
