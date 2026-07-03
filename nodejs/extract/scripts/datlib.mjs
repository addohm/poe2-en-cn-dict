// Core helpers for reading PoE2 .datc64 tables directly via the pathofexile-dat
// library internals, so we are not limited by the CLI's hardcoded language list
// (the CLI has no "Simplified Chinese" entry for PoE2).
import {
  FileLoader,
  BUNDLES_DIR,
} from "pathofexile-dat/bundles.js";
// Import the pure dat readers directly from the package's dist submodules.
// We deliberately avoid "pathofexile-dat/dat.js", because that aggregator also
// pulls in dat-analysis/wasm.js, which does an unsupported top-level file://
// fetch on load. These three submodules have no such dependency.
import { readDatFile } from "../node_modules/pathofexile-dat/dist/dat/dat-file.js";
import { readColumn } from "../node_modules/pathofexile-dat/dist/dat/reader.js";
import { getHeaderLength } from "../node_modules/pathofexile-dat/dist/dat/header.js";
import * as fs from "fs/promises";
import * as path from "path";

export const ValidFor = { PoE1: 1, PoE2: 2, Common: 3 };

// Minimal local bundle loader (reads files straight from an install dir).
class LocalBundleLoader {
  constructor(gameDir) {
    this.gameDir = gameDir;
    this.cache = new Map();
  }
  async fetchFile(name) {
    let bin = this.cache.get(name);
    if (!bin) {
      bin = await fs.readFile(path.join(this.gameDir, BUNDLES_DIR, name));
      this.cache.set(name, bin);
    }
    return bin;
  }
  clearBundleCache() {
    this.cache.clear();
  }
}

export async function loadClient(gameDir) {
  const loader = await FileLoader.create(new LocalBundleLoader(gameDir));
  return loader;
}

export async function loadSchema(schemaPath) {
  const raw = await fs.readFile(schemaPath, "utf-8");
  return JSON.parse(raw);
}

// Build the full ordered header list for a table (needed for correct byte
// offsets), mirroring pathofexile-dat's own importHeaders.
export function buildHeaders(tableSchema, datFile) {
  const headers = [];
  let offset = 0;
  let i = -1;
  for (const column of tableSchema.columns) {
    i++;
    const header = {
      // Synthesize a stable name for unnamed/unknown columns so every column
      // (including ones the community schema hasn't named yet) is addressable.
      name: column.name || `__col${i}`,
      offset,
      type: {
        array: column.array,
        interval: column.interval,
        integer:
          column.type === "u16" ? { unsigned: true, size: 2 }
          : column.type === "i16" ? { unsigned: false, size: 2 }
          : column.type === "u32" ? { unsigned: true, size: 4 }
          : column.type === "i32" ? { unsigned: false, size: 4 }
          : column.type === "enumrow" ? { unsigned: false, size: 4 }
          : undefined,
        decimal: column.type === "f32" ? { size: 4 } : undefined,
        string: column.type === "string" ? {} : undefined,
        boolean: column.type === "bool" ? {} : undefined,
        key:
          column.type === "row" || column.type === "foreignrow"
            ? { foreign: column.type === "foreignrow" }
            : undefined,
      },
      // keep original schema meta so callers can inspect localized/unique/etc.
      _schema: column,
    };
    headers.push(header);
    offset += getHeaderLength(header, datFile);
  }
  return headers;
}

// Read a table's requested columns from a given language path.
// Returns { rowCount, rows: [{ _index, <col>: value, ... }] } or null if the
// file does not exist at that path.
export async function readTable(loader, langPath, tableName, tableSchema, wantColumns) {
  const bytes = await loader.tryGetFileContents(`${langPath}/${tableName}.datc64`);
  if (!bytes) return null;
  const datFile = readDatFile(".datc64", bytes);
  const headers = buildHeaders(tableSchema, datFile);
  const picked = headers.filter((h) => wantColumns.includes(h.name) && h.name);
  const columns = picked.map((h) => ({ name: h.name, data: readColumn(h, datFile) }));
  const rows = Array(datFile.rowCount)
    .fill(undefined)
    .map((_, idx) => {
      const row = { _index: idx };
      for (const col of columns) row[col.name] = col.data[idx];
      return row;
    });
  return { rowCount: datFile.rowCount, rows };
}
