import dataclasses
import datetime
import math
import uuid

import numpy as np
import orjson
import pytest

import mojo_orjson as mojo


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        -42,
        (1 << 63) - 1,
        (1 << 64) - 1,
        0.0,
        -0.0,
        1.5,
        1e20,
        1e-6,
        1.2345e-5,
        float("nan"),
        float("inf"),
        "",
        "plain ASCII",
        'quote " slash \\ controls \b\t\n\f\r\x01',
        "Zażółć gęślą jaźń 控制",
        [],
        [1, "two", None, [False]],
        {},
        {"alpha": 1, "nested": {"items": [1, 2, 3]}},
    ],
)
def test_dumps_exact_scalar_and_container_parity(value):
    assert mojo.dumps(value) == orjson.dumps(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        123,
        -123.5e20,
        "escaped\ntext",
        "Unicode λ",
        [],
        [1, 2, {"x": False}],
        {},
        {"a": 1, "b": [2, 3], "c": {"d": None}},
    ],
)
def test_loads_parity_on_valid_documents(value):
    document = orjson.dumps(value)
    assert mojo.loads(document) == orjson.loads(document)
    assert mojo.loads(document.decode()) == orjson.loads(document.decode())
    assert mojo.loads(bytearray(document)) == orjson.loads(bytearray(document))
    assert mojo.loads(memoryview(document)) == orjson.loads(memoryview(document))


def test_duplicate_object_keys_last_value_wins():
    document = b'{"x":1,"x":2}'
    assert mojo.loads(document) == orjson.loads(document) == {"x": 2}


@pytest.mark.parametrize(
    "document",
    [
        b"",
        b" ",
        b"01",
        b"1.",
        b"1e",
        b"[1,]",
        b'{"a":}',
        b'{"a" 1}',
        b'{"a":1',
        b'"\x01"',
        b'"\\x20"',
        b'"\\uD800"',
        b"{} trailing",
        b"\xef\xbb\xbf{}",
        b'"\xff"',
    ],
)
def test_invalid_documents_raise_same_public_exception(document):
    with pytest.raises(mojo.JSONDecodeError):
        mojo.loads(document)
    with pytest.raises(orjson.JSONDecodeError):
        orjson.loads(document)


def test_decode_error_is_json_decode_error_and_value_error():
    with pytest.raises(mojo.JSONDecodeError) as caught:
        mojo.loads(b"[")
    assert isinstance(caught.value, ValueError)
    assert caught.value.pos == 1


def test_indent_sort_and_newline_exact_parity():
    value = {"z": [1, {"b": 2, "a": 1}], "a": {}}
    option = mojo.OPT_INDENT_2 | mojo.OPT_SORT_KEYS | mojo.OPT_APPEND_NEWLINE
    assert mojo.dumps(value, option=option) == orjson.dumps(value, option=option)


def test_non_str_keys_exact_parity():
    value = {
        1: "int",
        None: "none",
        1.25: "float",
        datetime.date(2024, 2, 3): "date",
        uuid.UUID(int=0): "uuid",
    }
    assert mojo.dumps(value, option=mojo.OPT_NON_STR_KEYS) == orjson.dumps(
        value, option=orjson.OPT_NON_STR_KEYS
    )


@pytest.mark.parametrize(
    "option",
    [
        0,
        mojo.OPT_NAIVE_UTC,
        mojo.OPT_UTC_Z,
        mojo.OPT_OMIT_MICROSECONDS,
        mojo.OPT_NAIVE_UTC | mojo.OPT_UTC_Z,
    ],
)
def test_datetime_date_time_and_uuid_parity(option):
    value = {
        "naive": datetime.datetime(2024, 2, 3, 4, 5, 6, 123456),
        "utc": datetime.datetime(2024, 2, 3, 4, 5, 6, tzinfo=datetime.timezone.utc),
        "date": datetime.date(2024, 2, 3),
        "time": datetime.time(4, 5, 6, 123456),
        "uuid": uuid.UUID("12345678-1234-5678-1234-567812345678"),
    }
    assert mojo.dumps(value, option=option) == orjson.dumps(value, option=option)


@dataclasses.dataclass
class Record:
    name: str
    count: int


def test_dataclass_default_serialization_parity():
    value = Record("sample", 3)
    assert mojo.dumps(value) == orjson.dumps(value)


def test_passthrough_dataclass_calls_default():
    value = Record("sample", 3)
    option = mojo.OPT_PASSTHROUGH_DATACLASS
    default = lambda item: {"fallback": item.name}
    assert mojo.dumps(value, default=default, option=option) == orjson.dumps(
        value, default=default, option=option
    )


def test_passthrough_datetime_calls_default():
    value = datetime.datetime(2024, 1, 1)
    default = lambda item: "custom-date"
    assert mojo.dumps(
        value, default=default, option=mojo.OPT_PASSTHROUGH_DATETIME
    ) == orjson.dumps(
        value, default=default, option=orjson.OPT_PASSTHROUGH_DATETIME
    )


def test_default_serializer_parity():
    class Custom:
        pass

    default = lambda _: {"converted": [1, 2]}
    assert mojo.dumps(Custom(), default=default) == orjson.dumps(Custom(), default=default)


@pytest.mark.parametrize("base,value", [(str, "x"), (int, 2), (list, [1, 2]), (dict, {"x": 1})])
def test_builtin_subclass_and_passthrough_parity(base, value):
    subclass = type("Subclass", (base,), {})
    item = subclass(value)
    assert mojo.dumps(item) == orjson.dumps(item)
    default = lambda obj: {"fallback": type(obj).__name__}
    assert mojo.dumps(
        item, default=default, option=mojo.OPT_PASSTHROUGH_SUBCLASS
    ) == orjson.dumps(
        item, default=default, option=orjson.OPT_PASSTHROUGH_SUBCLASS
    )


def test_float_and_tuple_subclasses_use_default_like_upstream():
    float_subclass = type("FloatSubclass", (float,), {})
    tuple_subclass = type("TupleSubclass", (tuple,), {})
    default = lambda obj: type(obj).__name__
    for item in (float_subclass(1.5), tuple_subclass((1, 2))):
        assert mojo.dumps(item, default=default) == orjson.dumps(item, default=default)


def test_non_callable_default_is_ignored_for_supported_values():
    assert mojo.dumps(1, default=1) == orjson.dumps(1, default=1)


def test_unsupported_type_raises_type_error():
    with pytest.raises(TypeError):
        mojo.dumps(object())
    with pytest.raises(TypeError):
        orjson.dumps(object())
    assert mojo.JSONEncodeError is TypeError


@pytest.mark.parametrize("value", [(1 << 63), -(1 << 63), 9007199254740992])
def test_strict_integer_parity(value):
    with pytest.raises(TypeError):
        mojo.dumps(value, option=mojo.OPT_STRICT_INTEGER)
    with pytest.raises(TypeError):
        orjson.dumps(value, option=orjson.OPT_STRICT_INTEGER)


def test_integer_64_bit_limits_parity():
    for value in (-(1 << 63) - 1, 1 << 64):
        with pytest.raises(TypeError):
            mojo.dumps(value)
        with pytest.raises(TypeError):
            orjson.dumps(value)


def test_numpy_array_and_scalars_parity():
    value = {
        "array": np.arange(12, dtype=np.int32).reshape(3, 4),
        "float": np.float64(1.25),
        "bool": np.bool_(True),
    }
    assert mojo.dumps(value, option=mojo.OPT_SERIALIZE_NUMPY) == orjson.dumps(
        value, option=orjson.OPT_SERIALIZE_NUMPY
    )


def test_numpy_float_widths_preserve_upstream_formatting():
    for dtype in (np.float16, np.float32, np.float64):
        value = dtype(1.23456789)
        array = np.array([[value]], dtype=dtype)
        assert mojo.dumps(value, option=mojo.OPT_SERIALIZE_NUMPY) == orjson.dumps(
            value, option=orjson.OPT_SERIALIZE_NUMPY
        )
        assert mojo.dumps(array, option=mojo.OPT_SERIALIZE_NUMPY) == orjson.dumps(
            array, option=orjson.OPT_SERIALIZE_NUMPY
        )


@pytest.mark.parametrize(
    "value",
    [
        np.array([object()], dtype=object),
        np.array([1 + 2j], dtype=np.complex64),
        np.array([1], dtype=">i4"),
        np.array(1, dtype=np.int64),
        np.longdouble("1.25"),
    ],
)
def test_unsupported_numpy_dtypes_are_rejected(value):
    with pytest.raises(TypeError):
        mojo.dumps(value, option=mojo.OPT_SERIALIZE_NUMPY)
    with pytest.raises(TypeError):
        orjson.dumps(value, option=orjson.OPT_SERIALIZE_NUMPY)


def test_noncontiguous_numpy_rejected():
    value = np.arange(20)[::2]
    with pytest.raises(TypeError):
        mojo.dumps(value, option=mojo.OPT_SERIALIZE_NUMPY)
    with pytest.raises(TypeError):
        orjson.dumps(value, option=orjson.OPT_SERIALIZE_NUMPY)


def test_fragment_is_embedded_verbatim_like_upstream():
    assert mojo.dumps({"raw": mojo.Fragment(b"[1,2]")}) == orjson.dumps(
        {"raw": orjson.Fragment(b"[1,2]")}
    )
    assert mojo.dumps(mojo.Fragment(b"{invalid}")) == orjson.dumps(
        orjson.Fragment(b"{invalid}")
    )


def test_fragment_rejects_bytearray():
    ours = mojo.Fragment(bytearray(b"1"))
    theirs = orjson.Fragment(bytearray(b"1"))
    with pytest.raises(TypeError):
        mojo.dumps(ours)
    with pytest.raises(TypeError):
        orjson.dumps(theirs)


def test_option_constants_match_upstream():
    for name in (
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
    ):
        assert getattr(mojo, name) == getattr(orjson, name)


def test_large_roundtrip_and_upstream_parity():
    value = [
        {"id": index, "name": f"row {index}", "active": index % 3 == 0, "score": math.sin(index)}
        for index in range(10_000)
    ]
    encoded = mojo.dumps(value)
    assert mojo.loads(encoded) == value
    assert mojo.loads(encoded) == orjson.loads(encoded)


@pytest.mark.parametrize("length", [0, 1, 15, 16, 17, 31, 32, 33, 63, 64, 65])
def test_simd_string_boundaries_and_scalar_tails(length):
    values = [
        "a" * length,
        "a" * length + '"',
        "a" * length + "\\",
        "a" * length + "\x01",
        "\x01" * length,
    ]
    for value in values:
        encoded = mojo.dumps(value)
        assert encoded == orjson.dumps(value)
        assert mojo.loads(encoded) == value


def test_simd_resumes_after_an_early_escape():
    value = '"' + "a" * 4097 + "\\" + "b" * 35
    assert mojo.dumps(value) == orjson.dumps(value)


def test_large_builtin_dump_path_and_guarded_fallbacks():
    values = [{"index": index, "value": index * 0.125} for index in range(4096)]
    assert mojo.dumps(values) == orjson.dumps(values)

    exponent_values = [1e-5] * 4096
    assert mojo.dumps(exponent_values) == orjson.dumps(exponent_values)

    invalid_keys = [{1: "value"}] * 4096
    with pytest.raises(mojo.JSONEncodeError):
        mojo.dumps(invalid_keys)
    with pytest.raises(orjson.JSONEncodeError):
        orjson.dumps(invalid_keys)


def test_large_document_validation_path_checks_risky_values():
    valid = orjson.dumps([index * 0.125 for index in range(10_000)])
    assert len(valid) > 64 * 1024
    assert mojo.loads(valid) == orjson.loads(valid)

    overflow = b"[" + b"0," * 33_000 + b"1e400]"
    with pytest.raises(mojo.JSONDecodeError):
        mojo.loads(overflow)
    with pytest.raises(orjson.JSONDecodeError):
        orjson.loads(overflow)

    lone_surrogate = b"[" + b'"plain",' * 10_000 + b'"\\ud800"]'
    with pytest.raises(mojo.JSONDecodeError):
        mojo.loads(lone_surrogate)
    with pytest.raises(orjson.JSONDecodeError):
        orjson.loads(lone_surrogate)


def test_flat_number_sequence_fast_path_preserves_range_errors():
    document = b"[1e400]"
    with pytest.raises(mojo.JSONDecodeError):
        mojo.loads(document)
    with pytest.raises(orjson.JSONDecodeError):
        orjson.loads(document)


def test_ffi_rejects_null_pointers_and_short_capacities():
    from mojo_orjson import _lib

    library = _lib.lib()
    assert library.morj_tokenize(0, 1, 0, 0, 0, 0) < 0

    ir = bytearray(b"\x08" + (4).to_bytes(8, "little") + b"null")
    ir_address = _lib.buffer_address(ir)
    destination = bytearray(4)
    assert library.morj_serialized_size(ir_address, len(ir) - 1, 0) < 0
    assert (
        library.morj_serialize(
            ir_address,
            len(ir),
            _lib.buffer_address(destination),
            len(destination) - 1,
            0,
        )
        < 0
    )
