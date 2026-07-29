from __future__ import annotations

import dataclasses
import datetime as _datetime
import json
import math
import uuid as _uuid
from typing import Any, Callable

from ._lib import serialize as _serialize
from ._lib import tokenize as _tokenize

__version__ = "0.1.0"

OPT_INDENT_2 = 1
OPT_NAIVE_UTC = 2
OPT_NON_STR_KEYS = 4
OPT_OMIT_MICROSECONDS = 8
OPT_SERIALIZE_NUMPY = 16
OPT_SORT_KEYS = 32
OPT_STRICT_INTEGER = 64
OPT_UTC_Z = 128
OPT_PASSTHROUGH_SUBCLASS = 256
OPT_PASSTHROUGH_DATETIME = 512
OPT_APPEND_NEWLINE = 1024
OPT_PASSTHROUGH_DATACLASS = 2048
OPT_SERIALIZE_DATACLASS = 0
OPT_SERIALIZE_UUID = 0

_VALID_OPTIONS = 4095
_LENGTH_BYTES = tuple(length.to_bytes(8, "little") for length in range(256))


JSONEncodeError = TypeError


class JSONDecodeError(json.JSONDecodeError):
    pass


class Fragment:
    def __init__(self, value: Any):
        self.value = value


def _raw(ir: bytearray, value: bytes) -> None:
    ir.append(8)
    ir.extend(_LENGTH_BYTES[len(value)] if len(value) < 256 else len(value).to_bytes(8, "little"))
    ir.extend(value)


def _string(ir: bytearray, value: str) -> None:
    data = value.encode("utf-8")
    ir.append(7)
    ir.extend(_LENGTH_BYTES[len(data)] if len(data) < 256 else len(data).to_bytes(8, "little"))
    ir.extend(data)


def _float_bytes(value: float) -> bytes:
    if not math.isfinite(value):
        return b"null"
    text = repr(value)
    if "e" in text:
        mantissa, exponent = text.split("e")
        sign = ""
        if exponent[0] in "+-":
            sign, exponent = exponent[0], exponent[1:]
        exponent = exponent.lstrip("0") or "0"
        numeric_exponent = int(sign + exponent)
        if -5 <= numeric_exponent < 0:
            negative = mantissa.startswith("-")
            digits = mantissa.lstrip("-").replace(".", "")
            text = ("-" if negative else "") + "0." + "0" * (-numeric_exponent - 1) + digits
        else:
            text = mantissa + "e" + sign + exponent
    return text.encode()


def _datetime_text(value: Any, option: int) -> str:
    if isinstance(value, _datetime.datetime):
        if option & OPT_OMIT_MICROSECONDS:
            value = value.replace(microsecond=0)
        text = value.isoformat()
        if value.tzinfo is None and option & OPT_NAIVE_UTC:
            text += "+00:00"
        if option & OPT_UTC_Z and text.endswith("+00:00"):
            text = text[:-6] + "Z"
        return text
    if isinstance(value, _datetime.time):
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise JSONEncodeError("datetime.time must not have tzinfo")
        if option & OPT_OMIT_MICROSECONDS:
            value = value.replace(microsecond=0)
        return value.isoformat()
    return value.isoformat()


def _dict_key(value: Any, option: int) -> str:
    if type(value) is str:
        return value
    if not option & OPT_NON_STR_KEYS:
        raise JSONEncodeError("Dict key must be str")
    if isinstance(value, str):
        return str(value)
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is float:
        return _float_bytes(value).decode()
    if isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
        return _datetime_text(value, option)
    if isinstance(value, _uuid.UUID):
        return str(value)
    raise JSONEncodeError("Dict key must a type serializable with OPT_NON_STR_KEYS")


class _Encoder:
    def __init__(self, default: Callable[[Any], Any] | None, option: int):
        self.default = default
        self.option = option
        self.ir = bytearray()
        self.depth = 0
        self.indent_extra = 0
        self.default_depth = 0
        self.key_ir: dict[str, bytes] = {}
        self.string_ir: dict[str, bytes] = {}

    def append_key(self, value: str) -> None:
        instruction = self.key_ir.get(value)
        if instruction is None:
            data = value.encode("utf-8")
            length = len(data)
            instruction = b"\x07" + (
                _LENGTH_BYTES[length] if length < 256 else length.to_bytes(8, "little")
            ) + data
            if length <= 64 and len(self.key_ir) < 2048:
                self.key_ir[value] = instruction
        self.ir.extend(instruction)

    def append_string(self, value: str) -> None:
        if len(value) > 64:
            _string(self.ir, value)
            return
        instruction = self.string_ir.get(value)
        if instruction is None:
            data = value.encode("utf-8")
            length = len(data)
            instruction = b"\x07" + (
                _LENGTH_BYTES[length] if length < 256 else length.to_bytes(8, "little")
            ) + data
            if len(self.string_ir) < 2048:
                self.string_ir[value] = instruction
        self.ir.extend(instruction)

    def encode(self, value: Any) -> None:
        if self.depth > 254:
            raise JSONEncodeError("Recursion limit reached")
        value_type = type(value)
        passthrough_subclass = self.option & OPT_PASSTHROUGH_SUBCLASS
        if value is None:
            _raw(self.ir, b"null")
        elif value_type is bool:
            _raw(self.ir, b"true" if value else b"false")
        elif value_type is str or isinstance(value, str) and not passthrough_subclass:
            self.append_string(str(value))
        elif value_type is int or isinstance(value, int) and not passthrough_subclass:
            number = int(value)
            if self.option & OPT_STRICT_INTEGER and abs(number) > 9007199254740991:
                raise JSONEncodeError("Integer exceeds 53-bit range")
            if number < -(1 << 63) or number > (1 << 64) - 1:
                raise JSONEncodeError("Integer exceeds 64-bit range")
            _raw(self.ir, str(number).encode())
        elif value_type is float:
            _raw(self.ir, _float_bytes(float(value)))
        elif value_type is list or isinstance(value, list) and not passthrough_subclass:
            self._sequence(value)
        elif value_type is tuple:
            self._sequence(value)
        elif value_type is dict or isinstance(value, dict) and not passthrough_subclass:
            self._mapping(value)
        elif isinstance(value, Fragment):
            if isinstance(value.value, str):
                fragment = value.value.encode("utf-8")
            elif isinstance(value.value, bytes):
                fragment = value.value
            else:
                raise JSONEncodeError("orjson.Fragment's content is not of type bytes or str")
            _raw(self.ir, fragment)
        elif isinstance(value, (_datetime.datetime, _datetime.date, _datetime.time)):
            if self.option & OPT_PASSTHROUGH_DATETIME:
                self._fallback(value)
            else:
                _string(self.ir, _datetime_text(value, self.option))
        elif isinstance(value, _uuid.UUID):
            _string(self.ir, str(value))
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            if self.option & OPT_PASSTHROUGH_DATACLASS:
                self._fallback(value)
            else:
                self._mapping({field.name: getattr(value, field.name) for field in dataclasses.fields(value)})
        elif self.option & OPT_SERIALIZE_NUMPY and value_type.__module__.startswith("numpy"):
            self._numpy(value)
        else:
            self._fallback(value)

    def _fallback(self, value: Any) -> None:
        if self.default is None:
            raise JSONEncodeError(f"Type is not JSON serializable: {type(value).__name__}")
        if self.default_depth >= 254:
            raise JSONEncodeError("default serializer exceeds recursion limit")
        self.default_depth += 1
        try:
            converted = self.default(value)
        except Exception as exc:
            raise JSONEncodeError("Type is not JSON serializable") from exc
        self.encode(converted)
        self.default_depth -= 1

    def _sequence(self, value: list[Any] | tuple[Any, ...]) -> None:
        self.ir.append(3)
        self.depth += 1
        for index, item in enumerate(value):
            if index:
                self.ir.append(5)
            if self.option & OPT_INDENT_2:
                self.indent_extra += 1 + self.depth * 2
            self.encode(item)
        self.depth -= 1
        if value and self.option & OPT_INDENT_2:
            self.indent_extra += 1 + self.depth * 2
        self.ir.append(4)

    def _mapping(self, value: dict[Any, Any]) -> None:
        if self.option & OPT_SORT_KEYS:
            pairs = [(_dict_key(key, self.option), item) for key, item in value.items()]
            pairs.sort(key=lambda pair: pair[0])
        else:
            pairs = value.items()
        self.ir.append(1)
        self.depth += 1
        for index, (key, item) in enumerate(pairs):
            if index:
                self.ir.append(5)
            if self.option & OPT_INDENT_2:
                self.indent_extra += 1 + self.depth * 2
            self.append_key(key if type(key) is str else _dict_key(key, self.option))
            self.ir.append(6)
            self.encode(item)
        self.depth -= 1
        if value and self.option & OPT_INDENT_2:
            self.indent_extra += 1 + self.depth * 2
        self.ir.append(2)

    def _numpy(self, value: Any) -> None:
        try:
            import numpy as np
        except ImportError:
            self._fallback(value)
            return
        if isinstance(value, np.ndarray):
            if not value.flags.c_contiguous:
                raise JSONEncodeError("numpy array is not C contiguous")
            if not value.dtype.isnative:
                raise JSONEncodeError("numpy array is not native-endianness")
            if value.dtype.kind not in "biuf":
                raise JSONEncodeError("unsupported datatype in numpy array")
            if value.ndim == 0:
                raise JSONEncodeError("unsupported numpy array with 0 dimensions")
            self.encode(list(value))
        elif isinstance(value, np.generic):
            if isinstance(value, np.bool_):
                self.encode(bool(value))
            elif isinstance(value, np.integer):
                self.encode(int(value))
            elif isinstance(value, np.float16):
                if np.isfinite(value):
                    self.encode(float(value))
                else:
                    _raw(self.ir, b"null")
            elif isinstance(value, np.float32):
                if np.isfinite(value):
                    _raw(self.ir, str(value).encode("ascii"))
                else:
                    _raw(self.ir, b"null")
            elif isinstance(value, np.float64):
                self.encode(float(value))
            else:
                self._fallback(value)
        else:
            self._fallback(value)


def dumps(obj: Any, /, default: Callable[[Any], Any] | None = None, option: int | None = None) -> bytes:
    if option is None:
        option = 0
    if type(option) is not int or option < 0 or option & ~_VALID_OPTIONS:
        raise JSONEncodeError("Invalid opts")
    encoder = _Encoder(default, option)
    try:
        encoder.encode(obj)
        result = _serialize(encoder.ir, bool(option & OPT_INDENT_2))
    except JSONEncodeError:
        raise
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise JSONEncodeError(str(exc)) from exc
    if option & OPT_APPEND_NEWLINE:
        result += b"\n"
    return result


class _Parser:
    def __init__(self, data: bytes, kinds: Any, starts: Any, ends: Any, count: int):
        self.data = data
        self.kinds = memoryview(kinds)
        self.starts = memoryview(starts)
        self.ends = memoryview(ends)
        self.count = count
        self.index = 0
        self.depth = 0
        self.string_cache: dict[bytes, str] = {}

    def error(self, message: str, index: int | None = None) -> None:
        if index is None:
            index = self.index
        pos = len(self.data) if index >= self.count else self.starts[index]
        document = self.data.decode("utf-8", "replace")
        raise JSONDecodeError(message, document, pos)

    def value(self) -> Any:
        if self.index >= self.count:
            self.error("unexpected end of data")
        kind = self.kinds[self.index]
        if kind == 1:
            return self.mapping()
        if kind == 3:
            return self.sequence()
        start = self.starts[self.index]
        end = self.ends[self.index]
        self.index += 1
        if kind == 7:
            raw = self.data[start + 1 : end - 1]
            if b"\\" not in raw:
                try:
                    cached = self.string_cache.get(raw)
                    if cached is not None:
                        return cached
                    value = raw.decode("utf-8")
                    if len(raw) <= 64 and len(self.string_cache) < 2048:
                        self.string_cache[raw] = value
                    return value
                except UnicodeDecodeError as exc:
                    self.error("invalid string", self.index - 1)
                    raise AssertionError from exc
            try:
                value = json.loads(self.data[start:end])
                value.encode("utf-8")
                return value
            except (ValueError, UnicodeError) as exc:
                self.error("invalid string", self.index - 1)
                raise AssertionError from exc
        if kind == 8:
            raw = self.data[start:end]
            if b"." in raw or b"e" in raw or b"E" in raw:
                value = float(raw)
                if not math.isfinite(value):
                    self.error("number is infinity when parsed as double", self.index - 1)
                return value
            value = int(raw)
            if value < -(1 << 63) or value > (1 << 64) - 1:
                self.error("number is out of range", self.index - 1)
            return value
        if kind == 9:
            return True
        if kind == 10:
            return False
        if kind == 11:
            return None
        self.error("unexpected character", self.index - 1)

    def sequence(self) -> list[Any]:
        if self.depth >= 1024:
            self.error("array and object recursion depth exceeded")
        self.depth += 1
        self.index += 1
        result = []
        if self.index < self.count and self.kinds[self.index] == 4:
            self.index += 1
            self.depth -= 1
            return result
        while True:
            if self.index >= self.count:
                self.error("unexpected end of data")
            kind = self.kinds[self.index]
            if kind == 8:
                start = self.starts[self.index]
                end = self.ends[self.index]
                self.index += 1
                raw = self.data[start:end]
                if b"." in raw or b"e" in raw or b"E" in raw:
                    item = float(raw)
                    if not math.isfinite(item):
                        self.error("number is infinity when parsed as double", self.index - 1)
                else:
                    item = int(raw)
                    if item < -(1 << 63) or item > (1 << 64) - 1:
                        self.error("number is out of range", self.index - 1)
                result.append(item)
            else:
                result.append(self.value())
            if self.index >= self.count:
                self.error("unexpected end of data")
            kind = self.kinds[self.index]
            self.index += 1
            if kind == 4:
                self.depth -= 1
                return result
            if kind != 5:
                self.error("expected comma or closing bracket", self.index - 1)

    def mapping(self) -> dict[str, Any]:
        if self.depth >= 1024:
            self.error("array and object recursion depth exceeded")
        self.depth += 1
        self.index += 1
        result = {}
        if self.index < self.count and self.kinds[self.index] == 2:
            self.index += 1
            self.depth -= 1
            return result
        while True:
            if self.index >= self.count or self.kinds[self.index] != 7:
                self.error("object keys must be strings")
            key = self.value()
            if self.index >= self.count or self.kinds[self.index] != 6:
                self.error("expected colon")
            self.index += 1
            result[key] = self.value()
            if self.index >= self.count:
                self.error("unexpected end of data")
            kind = self.kinds[self.index]
            self.index += 1
            if kind == 2:
                self.depth -= 1
                return result
            if kind != 5:
                self.error("expected comma or closing brace", self.index - 1)


def loads(obj: str | bytes | bytearray | memoryview, /) -> Any:
    if isinstance(obj, str):
        try:
            data = obj.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise JSONDecodeError("str is not valid UTF-8", obj, exc.start) from exc
    elif isinstance(obj, (bytes, bytearray, memoryview)):
        data = bytes(obj)
    else:
        raise JSONDecodeError("Input must be bytes, bytearray, memoryview, or str", "", 0)
    if data.startswith(b"\xef\xbb\xbf"):
        raise JSONDecodeError("unexpected UTF-8 BOM", data.decode("utf-8", "replace"), 0)
    kinds, starts, ends, count = _tokenize(data)
    if count < 0:
        pos = min(-count - 1, len(data))
        raise JSONDecodeError("unexpected character", data.decode("utf-8", "replace"), pos)
    parser = _Parser(data, kinds, starts, ends, count)
    value = parser.value()
    if parser.index != count:
        parser.error("unexpected content after document")
    return value


__all__ = [
    "dumps",
    "loads",
    "Fragment",
    "JSONEncodeError",
    "JSONDecodeError",
    "OPT_APPEND_NEWLINE",
    "OPT_INDENT_2",
    "OPT_NAIVE_UTC",
    "OPT_NON_STR_KEYS",
    "OPT_OMIT_MICROSECONDS",
    "OPT_PASSTHROUGH_DATACLASS",
    "OPT_PASSTHROUGH_DATETIME",
    "OPT_PASSTHROUGH_SUBCLASS",
    "OPT_SERIALIZE_DATACLASS",
    "OPT_SERIALIZE_NUMPY",
    "OPT_SERIALIZE_UUID",
    "OPT_SORT_KEYS",
    "OPT_STRICT_INTEGER",
    "OPT_UTC_Z",
]
