import * as fs from "fs/promises";
import * as path from "path";
const D = path.resolve(process.cwd(), "..", "dictionary", "lookup");
const e2c = JSON.parse(await fs.readFile(path.join(D, "en_to_cn.json"), "utf-8"));
const c2e = JSON.parse(await fs.readFile(path.join(D, "cn_to_en.json"), "utf-8"));
const e2cM = JSON.parse(await fs.readFile(path.join(D, "en_to_cn.multi.json"), "utf-8"));

const enTerms = process.argv.slice(2).filter((a) => !/[一-鿿]/.test(a));
const zhTerms = process.argv.slice(2).filter((a) => /[一-鿿]/.test(a));
console.log("EN -> CN:");
for (const t of enTerms) console.log(`  ${t}  =>  ${e2c[t] ?? "(none)"}${e2cM[t] ? "   [multi: " + e2cM[t].map((v) => v.target + "×" + v.count).join(", ") + "]" : ""}`);
console.log("CN -> EN:");
for (const t of zhTerms) console.log(`  ${t}  =>  ${c2e[t] ?? "(none)"}`);
