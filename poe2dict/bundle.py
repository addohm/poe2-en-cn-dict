"""Bundle index parsing + file extraction (Python port of pathofexile-dat).

Reads a PoE2 install's Bundles2/_.index.bin, and extracts individual files by
their virtual path, decompressing the Oodle bundles via `ooz`.
"""
import os
import struct
from .ooz import Ooz

BUNDLES_DIR = "Bundles2"
MASK64 = (1 << 64) - 1

# --- bundle chunk header offsets (see bundle.js) ---
_S_DECOMP_SIZE = 0
_S_CHUNK_COUNT = 36
_S_GRANULARITY = 40
_S_CHUNK_SIZES = 60


def _i32(buf, off):
    return struct.unpack_from("<i", buf, off)[0]


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def murmur64a(s: str) -> bytes:
    """MurmurHash64A as used by GGP bundle index (seed 0x1337b33f)."""
    data = s.encode("utf-8")
    m = 0xC6A4A7935BD1E995
    r = 47
    length = len(data)
    h = (0x1337B33F ^ ((length * m) & MASK64)) & MASK64
    n8 = length & ~7
    for i in range(0, n8, 8):
        k = int.from_bytes(data[i : i + 8], "little")
        k = (k * m) & MASK64
        k ^= k >> r
        k = (k * m) & MASK64
        h ^= k
        h = (h * m) & MASK64
    rem = length & 7
    if rem:
        tail = data[n8:]
        for j in range(rem):
            h ^= tail[j] << (8 * j)
        h = (h * m) & MASK64
    h ^= h >> r
    h = (h * m) & MASK64
    h ^= h >> r
    return h.to_bytes(8, "little")


def decompress_whole_bundle(ooz: Ooz, bundle: bytes) -> bytes:
    total = _i32(bundle, _S_DECOMP_SIZE)
    chunks_count = _i32(bundle, _S_CHUNK_COUNT)
    granularity = _i32(bundle, _S_GRANULARITY)
    chunk_begin = _S_CHUNK_SIZES + chunks_count * 4
    out = bytearray(total)
    dec_off = 0
    for idx in range(chunks_count):
        chunk_size = _i32(bundle, _S_CHUNK_SIZES + idx * 4)
        chunk = bundle[chunk_begin : chunk_begin + chunk_size]
        dec_chunk_size = (total % granularity) if idx == chunks_count - 1 else granularity
        raw = ooz.decompress(chunk, dec_chunk_size)
        out[dec_off : dec_off + dec_chunk_size] = raw
        dec_off += dec_chunk_size
        chunk_begin += chunk_size
    return bytes(out)


def read_index_bundle(b: bytes):
    off = 0
    bundles_count = _i32(b, off); off += 4
    begin = off
    for _ in range(bundles_count):
        name_len = _i32(b, off)
        off += 4 + name_len + 4
    bundles_info = b[begin:off]

    files_count = _i32(b, off); off += 4
    fbegin = off
    off += files_count * (8 + 4 + 4 + 4)
    files_info = b[fbegin:off]

    dirs_count = _i32(b, off); off += 4
    dbegin = off
    off += dirs_count * (8 + 4 + 4 + 4)
    dirs_info = b[dbegin:off]

    path_reps_bundle = b[off:]
    return {
        "bundles_info": bundles_info,
        "files_info": files_info,
        "dirs_info": dirs_info,
        "path_reps_bundle": path_reps_bundle,
    }


def _bundle_name(bundles_info: bytes, bundle_idx: int) -> str:
    off = 0
    for _ in range(bundle_idx):
        name_len = _i32(bundles_info, off)
        off += 4 + name_len + 4
    name_len = _i32(bundles_info, off)
    off += 4
    return bundles_info[off : off + name_len].decode("utf-8")


def get_file_info(path: str, bundles_info: bytes, files_info: bytes):
    """Return (bundle_filename, offset, size) or None."""
    h = murmur64a(path.lower())
    struct_offset = files_info.find(h)
    if struct_offset == -1:
        return None
    bundle_idx = _i32(files_info, struct_offset + 8)
    offset_in_bundle = _i32(files_info, struct_offset + 12)
    file_size = _i32(files_info, struct_offset + 16)
    name = _bundle_name(bundles_info, bundle_idx)
    return (name + ".bundle.bin", offset_in_bundle, file_size)


def unpack_paths(data: bytes):
    off = 0
    base_mode = False
    bases = []
    paths = []
    n = len(data)
    while off <= n - 4:
        idx = _i32(data, off) - 1
        off += 4
        if idx == -1:
            base_mode = not base_mode
            if base_mode:
                bases = []
        else:
            nul = data.index(0, off)
            s = data[off:nul].decode("utf-8")
            off = nul + 1
            if idx < len(bases):
                s = bases[idx] + s
            if base_mode:
                bases.append(s)
            else:
                paths.append(s)
    return paths


def get_dir_content(dir_path: str, path_reps: bytes, dirs_info: bytes):
    """Return (files, dirs) full-path lists for a directory (case-sensitive key)."""
    struct = 20  # 8-byte hash + 3x int32
    h = murmur64a(dir_path)  # NB: directory keys are hashed WITHOUT lowercasing
    off = dirs_info.find(h)
    if off == -1:
        raise KeyError(dir_path)
    base = _i32(dirs_info, off + 8)
    size = _i32(dirs_info, off + 12)
    all_size = _i32(dirs_info, off + 16)
    files = unpack_paths(path_reps[base : base + size])
    children_start = base + size
    children_end = base + all_size
    dirs = set()
    for i in range(len(dirs_info) // struct):
        o = _i32(dirs_info, struct * i + 8)
        sz = _i32(dirs_info, struct * i + 12)
        if o < children_start or (o + sz) > children_end:
            continue
        o2 = o + 4  # consume BASE_MODE ON marker
        if _i32(path_reps, o2) == 0:  # BASE_MODE OFF immediately -> no files
            continue
        o2 += 4
        nul = path_reps.index(0, o2)
        basepath = path_reps[o2:nul].decode("utf-8")
        if not basepath.startswith(dir_path):
            continue
        slash = basepath.find("/", len(dir_path) + 1)
        if slash != -1:
            dirs.add(basepath[:slash])
    return files, sorted(dirs)


class FileLoader:
    def __init__(self, game_dir: str, ooz: Ooz):
        self.dir = game_dir
        self.ooz = ooz
        self._raw = {}   # bundle filename -> compressed bytes
        self._dec = {}   # bundle filename -> decompressed bytes
        self._path_reps_cache = None
        idx_bin = self._fetch("_.index.bin")
        idx = decompress_whole_bundle(ooz, idx_bin)
        self.index = read_index_bundle(idx)

    def _fetch(self, name: str) -> bytes:
        b = self._raw.get(name)
        if b is None:
            with open(os.path.join(self.dir, BUNDLES_DIR, name), "rb") as f:
                b = f.read()
            self._raw[name] = b
        return b

    def _decompressed(self, name: str) -> bytes:
        d = self._dec.get(name)
        if d is None:
            d = decompress_whole_bundle(self.ooz, self._fetch(name))
            self._dec[name] = d
        return d

    def try_get_file(self, path: str):
        info = get_file_info(path, self.index["bundles_info"], self.index["files_info"])
        if info is None:
            return None
        name, off, size = info
        dec = self._decompressed(name)
        return dec[off : off + size]

    def _path_reps(self) -> bytes:
        if self._path_reps_cache is None:
            self._path_reps_cache = decompress_whole_bundle(self.ooz, self.index["path_reps_bundle"])
        return self._path_reps_cache

    def list_dir(self, dir_path: str):
        return get_dir_content(dir_path, self._path_reps(), self.index["dirs_info"])

    def iter_files(self, root: str):
        """Recursively yield every file path (lowercased virtual path) under root."""
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                files, dirs = self.list_dir(d)
            except KeyError:
                continue
            for f in files:
                yield f
            stack.extend(dirs)
