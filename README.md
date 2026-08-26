# mojo-orjson

`mojo-orjson` is an experimental, standalone Mojo port of the compute-heavy byte
paths in [orjson](https://github.com/ijl/orjson). It exposes the familiar
`dumps(obj, default=None, option=None)` and `loads(obj)` Python API while a single
Mojo shared library performs JSON tokenization, lexical validation, string
escaping, and final byte emission.

The Python compatibility layer still walks input objects and materializes parsed
objects. That boundary dominates container-heavy end-to-end runtime, while the
Mojo byte kernel is competitive on large contiguous strings.

## Covered subset

- `dumps()` for `None`, booleans, signed/unsigned 64-bit integers, floats, strings,
  lists, tuples, dictionaries, dataclasses, `datetime`, `date`, `time`, UUID, and
  C-contiguous native-endian NumPy boolean, integer, `float16`, `float32`, and
  `float64` arrays/scalars
- `loads()` from `str`, `bytes`, `bytearray`, and `memoryview`, producing native
  dictionaries, lists, strings, integers, floats, booleans, and `None`
- UTF-8 input validation, JSON number grammar, escape validation, duplicate-key
  behavior, non-finite float serialization, and signed/unsigned 64-bit limits
- `Fragment`, `JSONEncodeError`, `JSONDecodeError`, and all upstream `OPT_*`
  constant names
- Behavior for `OPT_APPEND_NEWLINE`, `OPT_INDENT_2`, `OPT_NAIVE_UTC`,
  `OPT_NON_STR_KEYS`, `OPT_OMIT_MICROSECONDS`, `OPT_PASSTHROUGH_DATACLASS`,
  `OPT_PASSTHROUGH_DATETIME`, `OPT_PASSTHROUGH_SUBCLASS`,
  `OPT_SERIALIZE_NUMPY`, `OPT_SORT_KEYS`, `OPT_STRICT_INTEGER`, and `OPT_UTC_Z`

The 101-test suite compares results and serialized bytes directly with upstream
`orjson` 3.11.9. It includes valid and invalid JSON, nested documents, options,
timestamps, dataclasses, fragments, NumPy values, numeric limits, and a 10,000-row
round trip. SIMD-width boundaries, scalar tails, dense escape expansion, and the
flat-number materialization fast path have dedicated coverage.

This is not a drop-in replacement for all of upstream orjson. Not covered are
upstream's exact diagnostic wording/position for every malformed document,
datetime64 NumPy arrays, non-native-endian or non-contiguous arrays, complex,
object, extended-precision, and timedelta NumPy dtypes, every third-party `tzinfo`
implementation, upstream's internal recursion-limit details, or platform wheels.
The package must be imported as `mojo_orjson`; it deliberately does not shadow an
installed `orjson`, which remains available for parity testing.

## Install

```bash
pixi install
pixi run build
pixi run test
```

The Mojo version is pinned in `pixi.toml`. The build creates
`dist/libmojo-orjson.so`.

## Usage

Run this from the repository root after building:

```bash
pixi run python - <<'PY'
import mojo_orjson as orjson

payload = {
    "project": "mojo-orjson",
    "values": [1, 2, 3],
    "ready": True,
}
encoded = orjson.dumps(
    payload,
    option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
)
print(encoded.decode())
assert orjson.loads(encoded) == payload
PY
```

## Benchmark

Measured with `pixi run bench` on an Intel Xeon E5-2697 v4 at 2.30 GHz,
Python 3.13.14, Mojo `1.1.0.dev2026081105`, and orjson 3.11.9. Values are the
median of five warm runs. A relative value below `1.00x` means `mojo-orjson` is
slower.

| Case | mojo-orjson | orjson | Relative |
|---|---:|---:|---:|
| dumps 100k records | 526.95 ms | 22.31 ms | 0.04x (slower) |
| dumps 9 MB ASCII string | 4.99 ms | 7.93 ms | 1.59x (faster) |
| loads 100k records | 251.38 ms | 153.43 ms | 0.61x (slower) |
| loads 500k numbers | 104.92 ms | 33.85 ms | 0.32x (slower) |

Upstream orjson performs traversal, parsing, and object construction inside one
mature Rust extension. Here every value crosses a Python loop before or after the
Mojo byte kernel. The benchmark is useful primarily as a profile of that remaining
porting boundary; it does not demonstrate an end-to-end speedup.

## How it works

For serialization, top-level strings go directly from their UTF-8 buffer through
the Mojo sizing and emission kernels without an instruction-buffer copy. Large
built-in containers first use CPython's C encoder, then a Mojo lexical pass accepts
the result only when its types, ranges, depth, and float spelling are orjson-compatible;
otherwise serialization falls back to the general path. That path walks the object
graph into a compact instruction buffer and caches repeated short strings and keys.
Mojo uses the host SIMD width to classify and copy ordinary string runs, resumes
SIMD after escapes, and handles the remainder with a scalar tail.

For parsing, UTF-8 JSON bytes pass to a Mojo tokenizer. Its string scanner skips
host-width runs with SIMD loads and reductions and validates escapes, controls,
number grammar, and integer ranges. Documents of at least 64 KiB use a zero-allocation
Mojo validation pass followed by CPython's C materializer; only lexically risky
floats or escaped Unicode require an additional result check. Smaller inputs retain
the token-array materializer, its decoded-string cache, and flat-number specialization.

The C ABI exports only non-parametric functions. All buffers cross `ctypes` as
integer addresses with explicit lengths and output capacities and are reconstructed in Mojo as
`UnsafePointer[..., AnyOrigin[mut=True]]`; allocation and ownership stay entirely
on the Python side. Calls are synchronous, and Python retains references to every
buffer for the complete call. Immutable Python `bytes` input and contiguous,
exact-dtype NumPy token buffers cross the FFI boundary without an intermediate
copy.

No threaded or GPU path is provided. Tokenization, structural formatting, and
Python object construction carry sequential JSON state, while the independent
byte scans are memory-bound and have effectively no floating-point arithmetic.
Their arithmetic intensity is below the threshold that could repay device
transfer and launch costs, so a GPU path would be expected to lose rather than
accelerate this workload.

MIT licensed.
