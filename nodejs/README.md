# Node.js implementation

An alternative generator for the dictionary, built on the
[`pathofexile-dat`](https://www.npmjs.com/package/pathofexile-dat) library. It
produces the **same `dictionary/` output** as the Python implementation at the
repo root (validated byte-for-byte).

Windows only (uses PowerShell wrappers + a portable Node download). The Chinese
client only runs on Windows anyway.

## Usage

```powershell
# 1. One-time setup: portable Node + pathofexile-dat (no admin, nothing global).
powershell -File setup.ps1

# 2. Build / refresh (run after any game patch).
powershell -File update.ps1
```

- Reads install paths from the shared [`../config.json`](../config.json).
- Writes to the shared [`../dictionary/`](../dictionary/).
- Override installs: `powershell -File update.ps1 -Cn "D:\PoE2 CN" -Intl "E:\...\Path of Exile 2"`.
- Ad-hoc lookups: `cd extract; ..\tools\node\node.exe scripts\query.mjs "Dexterity" "闪避"`.

## Layout

```
nodejs/
├─ setup.ps1                     portable Node + pathofexile-dat install
├─ update.ps1                    fetch schema + build (writes ../dictionary)
├─ tools/node/                   portable Node runtime (created by setup.ps1)
└─ extract/
   ├─ node_modules/             pathofexile-dat + deps (created by setup.ps1)
   ├─ cache/schema.min.json     fetched dat-schema
   ├─ dictionary_README.md      consumer docs copied into the output
   └─ scripts/
      ├─ datlib.mjs             low-level .datc64 reader (library wrapper)
      ├─ build.mjs              extractor + dictionary builder
      ├─ query.mjs              CLI lookup helper
      └─ list_langs.mjs         diagnostic: list a client's language folders
```

See the [root README](../README.md) for how the extraction works and the
[dictionary format docs](../dictionary/README.md) for the output.
