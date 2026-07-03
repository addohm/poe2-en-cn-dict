// Enumerates the directory tree of a PoE2 install's bundle index so we can see
// which language folders each client actually ships. Usage:
//   node list_langs.mjs "<game install dir>" [startDir] [maxDepth]
import {
  decompressSliceInBundle,
  decompressedBundleSize,
  readIndexBundle,
  getDirContent,
  getRootDirs,
  BUNDLES_DIR,
} from "pathofexile-dat/bundles.js";
import * as fs from "fs/promises";
import * as path from "path";

const gameDir = process.argv[2];
const startDir = process.argv[3] ?? null;
const maxDepth = Number(process.argv[4] ?? 2);
if (!gameDir) {
  console.error('Usage: node list_langs.mjs "<install dir>" [startDir] [maxDepth]');
  process.exit(1);
}

async function decompress(bin) {
  const out = new Uint8Array(decompressedBundleSize(bin));
  decompressSliceInBundle(bin, 0, out);
  return out;
}

const indexBin = await fs.readFile(path.join(gameDir, BUNDLES_DIR, "_.index.bin"));
const indexBundle = await decompress(indexBin);
const { dirsInfo, pathRepsBundle } = readIndexBundle(indexBundle);
const pathReps = await decompress(pathRepsBundle);

function content(dir) {
  try {
    return getDirContent(dir, pathReps, dirsInfo);
  } catch {
    return null;
  }
}

const roots = getRootDirs(pathReps, dirsInfo);
console.log("ROOT DIRS:", roots);

function walk(dir, depth) {
  const c = content(dir);
  if (!c) return;
  const datc = c.files.filter((f) => f.endsWith(".datc64")).length;
  console.log(
    `${"  ".repeat(depth)}${dir}/  [dirs:${c.dirs.length} files:${c.files.length} datc64:${datc}]`
  );
  if (depth >= maxDepth) return;
  for (const d of c.dirs.sort()) walk(d, depth + 1);
}

for (const start of startDir ? [startDir] : roots) walk(start, 0);
