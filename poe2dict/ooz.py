"""Oodle (Kraken) decompression via the vendored ooz.wasm, driven by wasmtime.

This is a Python port of the `ooz-wasm` JS glue. The wasm module (minified,
Emscripten) exposes:
    imports  a.a = emscripten_resize_heap(i32) -> i32
             a.b = emscripten_memcpy_js(i32, i32, i32) -> ()
    exports  c = memory
             d = __wasm_call_ctors()
             e = malloc(i32) -> i32
             f = free(i32) -> ()
             g = Kraken_Decompress(src, srcLen, dst, dstLen) -> i32
"""
import os
from wasmtime import Engine, Store, Module, Instance, Func, FuncType, ValType

_WASM = os.path.join(os.path.dirname(__file__), "vendor", "ooz.wasm")
_OOZ_SAFE_SPACE = 64
_PAGE = 65536


class Ooz:
    def __init__(self, wasm_path=_WASM):
        self.engine = Engine()
        self.store = Store(self.engine)
        self.module = Module.from_file(self.engine, wasm_path)
        self._mem = None  # set after instantiation; imports close over self

        i32 = ValType.i32()

        def resize_heap(requested):
            mem = self._mem
            cur = mem.data_len(self.store)
            if requested <= cur:
                return 1
            delta = (requested - cur + _PAGE - 1) // _PAGE
            try:
                mem.grow(self.store, delta)
                return 1
            except Exception:
                return 0

        def memcpy_js(dest, src, num):
            if num <= 0:
                return
            mem = self._mem
            chunk = mem.read(self.store, src, src + num)
            mem.write(self.store, chunk, dest)

        resize_fn = Func(self.store, FuncType([i32], [i32]), resize_heap)
        memcpy_fn = Func(self.store, FuncType([i32, i32, i32], []), memcpy_js)

        # Import order must match module.imports: a.a then a.b
        self.instance = Instance(self.store, self.module, [resize_fn, memcpy_fn])
        exports = self.instance.exports(self.store)
        self._mem = exports["c"]
        self._call_ctors = exports["d"]
        self._malloc = exports["e"]
        self._free = exports["f"]
        self._kraken = exports["g"]
        self._call_ctors(self.store)

    def decompress(self, data: bytes, raw_size: int) -> bytes:
        """Decompress `data` to exactly `raw_size` bytes."""
        store = self.store
        mem = self._mem
        comp_ptr = self._malloc(store, len(data))
        mem.write(store, data, comp_ptr)
        dst_ptr = self._malloc(store, raw_size + _OOZ_SAFE_SPACE)
        try:
            res = self._kraken(store, comp_ptr, len(data), dst_ptr, raw_size)
            if res < 0:
                raise RuntimeError("Kraken_Decompress failed")
            if res != raw_size:
                raise RuntimeError(f"decompressed size {res} != expected {raw_size}")
            return bytes(mem.read(store, dst_ptr, dst_ptr + raw_size))
        finally:
            self._free(store, comp_ptr)
            self._free(store, dst_ptr)
