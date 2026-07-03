"""datc64 table reader (Python port of pathofexile-dat's dat/* modules).

Only the pieces needed to build the dictionary are implemented in full: every
column's *size* (to compute byte offsets) and reading of *string* columns
(scalar and array). Non-string columns are sized but not decoded.
"""
import struct

_VDATA_MAGIC = b"\xbb" * 8
_MEMSIZE = 8
_FOUR_ZERO = b"\x00\x00\x00\x00"

# datc64 field sizes
_SIZE_BOOL = 1
_SIZE_STRING = 8       # uint16_t*
_SIZE_KEY = 8          # size_t
_SIZE_KEY_FOREIGN = 16
_SIZE_ARRAY = 16       # { size_t length; size_t offset; }

_INT_SIZE = {"u16": 2, "i16": 2, "u32": 4, "i32": 4, "enumrow": 4}
_INT_UNSIGNED = {"u16", "u32"}


class DatFile:
    __slots__ = ("row_count", "row_length", "fixed", "variable")

    def __init__(self, row_count, row_length, fixed, variable):
        self.row_count = row_count
        self.row_length = row_length
        self.fixed = fixed
        self.variable = variable


def read_dat_file(data: bytes) -> DatFile:
    if len(data) < 4 + len(_VDATA_MAGIC):
        raise ValueError("Invalid file size.")
    row_count = struct.unpack_from("<I", data, 0)[0]
    body = data[4:]
    boundary = _find_aligned(body, _VDATA_MAGIC, row_count)
    if boundary == -1:
        raise ValueError("variable-data section not found")
    row_length = (boundary // row_count) if row_count > 0 else 0
    fixed = body[:boundary]
    variable = body[boundary:]
    return DatFile(row_count, row_length, fixed, variable)


def _find_aligned(data: bytes, seq: bytes, element_count: int) -> int:
    from_index = 0
    while True:
        idx = data.find(seq, from_index)
        if idx == -1:
            return -1
        if element_count == 0 or idx % element_count == 0:
            return idx
        from_index = idx + 1


def _read_string_at(variable: bytes, offset: int) -> str:
    end = variable.find(_FOUR_ZERO, offset)
    if end < 0:
        return ""
    while (end - offset) % 2 != 0:
        end = variable.find(_FOUR_ZERO, end + 1)
        if end < 0:
            return ""
    return variable[offset:end].decode("utf-16-le", errors="replace")


def column_type(col: dict) -> dict:
    """Normalise a schema column into a size/kind descriptor."""
    t = col.get("type")
    return {
        "array": bool(col.get("array")),
        "interval": bool(col.get("interval")),
        "string": t == "string",
        "boolean": t == "bool",
        "int_size": _INT_SIZE.get(t),
        "decimal_size": 4 if t == "f32" else None,
        "key": t in ("row", "foreignrow"),
        "key_foreign": t == "foreignrow",
    }


def header_length(ct: dict) -> int:
    count = 2 if ct["interval"] else 1
    if ct["array"]:
        return _SIZE_ARRAY
    if ct["string"]:
        return _SIZE_STRING
    if ct["key"]:
        return _SIZE_KEY_FOREIGN if ct["key_foreign"] else _SIZE_KEY
    if ct["int_size"] is not None:
        return ct["int_size"] * count
    if ct["decimal_size"] is not None:
        return ct["decimal_size"] * count
    if ct["boolean"]:
        return _SIZE_BOOL
    raise ValueError("Corrupted header")


def build_headers(columns: list) -> list:
    """Return [{name, offset, ct}] for every column, computing byte offsets.

    Unnamed columns get a synthesized stable name so they remain addressable.
    """
    headers = []
    offset = 0
    for i, col in enumerate(columns):
        ct = column_type(col)
        headers.append({"name": col.get("name") or f"__col{i}", "offset": offset, "ct": ct})
        offset += header_length(ct)
    return headers


def read_string_column(header: dict, datf: DatFile) -> list:
    """Read a string column (scalar or array of strings) for all rows."""
    ct = header["ct"]
    base = header["offset"]
    rl = datf.row_length
    fixed = datf.fixed
    variable = datf.variable
    out = []
    if ct["array"]:
        for row in range(datf.row_count):
            off = row * rl + base
            length = struct.unpack_from("<I", fixed, off)[0]
            if length == 0:
                out.append([])
                continue
            var_off = struct.unpack_from("<I", fixed, off + _MEMSIZE)[0]
            arr = []
            for e in range(length):
                str_ptr = struct.unpack_from("<I", variable, var_off + e * _SIZE_STRING)[0]
                arr.append(_read_string_at(variable, str_ptr))
            out.append(arr)
    else:
        for row in range(datf.row_count):
            off = row * rl + base
            str_ptr = struct.unpack_from("<I", fixed, off)[0]
            out.append(_read_string_at(variable, str_ptr))
    return out
