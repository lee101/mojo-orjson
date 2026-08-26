from __future__ import annotations

import ctypes
import os
import subprocess

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.join(ROOT, "dist", "libmojo-orjson.so")

I = ctypes.c_int64
_SIGNATURES = {
    "morj_tokenize": ([I, I, I, I, I, I], I),
    "morj_validate": ([I, I], I),
    "morj_stdlib_compatible": ([I, I], I),
    "morj_string_size": ([I, I], I),
    "morj_write_string": ([I, I, I, I], I),
    "morj_serialized_size": ([I, I, I], I),
    "morj_serialize": ([I, I, I, I, I], I),
}
_lib: ctypes.CDLL | None = None
_pybytes_as_string = ctypes.pythonapi.PyBytes_AsString
_pybytes_as_string.argtypes = [ctypes.py_object]
_pybytes_as_string.restype = ctypes.c_void_p
_pybytes_from_size = ctypes.pythonapi.PyBytes_FromStringAndSize
_pybytes_from_size.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t]
_pybytes_from_size.restype = ctypes.py_object


class BuildError(RuntimeError):
    pass


def build() -> str:
    if not os.path.exists(LIB):
        proc = subprocess.run(
            ["bash", os.path.join(ROOT, "build", "build.sh")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if proc.returncode or not os.path.exists(LIB):
            raise BuildError((proc.stderr or proc.stdout).strip())
    return LIB


def lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(build())
        for name, (argtypes, restype) in _SIGNATURES.items():
            fn = getattr(_lib, name)
            fn.argtypes = argtypes
            fn.restype = restype
    return _lib


def buffer_address(data: bytearray) -> int:
    if not data:
        raise ValueError("cannot take the address of an empty buffer")
    return ctypes.addressof((ctypes.c_ubyte * len(data)).from_buffer(data))


def tokenize(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    count_max = max(len(data), 1)
    kinds = np.empty(count_max, dtype=np.uint8)
    starts = np.empty(count_max, dtype=np.int64)
    ends = np.empty(count_max, dtype=np.int64)
    count = lib().morj_tokenize(
        _pybytes_as_string(data),
        len(data),
        kinds.ctypes.data,
        starts.ctypes.data,
        ends.ctypes.data,
        count_max,
    )
    if count > count_max:
        raise RuntimeError("tokenizer returned more tokens than output capacity")
    return kinds, starts, ends, count


def validate(data: bytes) -> int:
    return lib().morj_validate(_pybytes_as_string(data), len(data))


def stdlib_compatible(data: bytes) -> bool:
    return bool(lib().morj_stdlib_compatible(_pybytes_as_string(data), len(data)))


def serialize_string(data: bytes) -> bytes:
    library = lib()
    source = _pybytes_as_string(data)
    size = library.morj_string_size(source, len(data))
    if size < 0:
        raise RuntimeError("serializer rejected string")
    destination = _pybytes_from_size(None, size)
    written = library.morj_write_string(
        source,
        len(data),
        _pybytes_as_string(destination),
        size,
    )
    if written != size:
        raise RuntimeError("serializer size mismatch")
    return destination


def serialize(ir: bytearray, indent: bool) -> bytes:
    library = lib()
    ir_address = buffer_address(ir)
    size = library.morj_serialized_size(ir_address, len(ir), int(indent))
    if size < 0:
        raise RuntimeError("serializer rejected invalid instruction buffer")
    destination = _pybytes_from_size(None, size)
    written = library.morj_serialize(
        ir_address,
        len(ir),
        _pybytes_as_string(destination),
        size,
        int(indent),
    )
    if written != size:
        raise RuntimeError("serializer size mismatch")
    return destination
