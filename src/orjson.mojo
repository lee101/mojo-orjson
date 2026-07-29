"""JSON tokenizer and byte serializer exposed through a stable C ABI."""

from std.sys.info import simd_width_of

comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = UnsafePointer[Int64, AnyOrigin[mut=True]]
comptime W = simd_width_of[DType.uint8]()


def is_ws(c: UInt8) -> Bool:
    return c == 32 or c == 9 or c == 10 or c == 13


def is_digit(c: UInt8) -> Bool:
    return c >= 48 and c <= 57


def is_hex(c: UInt8) -> Bool:
    return (
        (c >= 48 and c <= 57) or (c >= 65 and c <= 70) or (c >= 97 and c <= 102)
    )


def emit(
    kinds: BPtr,
    starts: IPtr,
    ends: IPtr,
    count: Int,
    kind: UInt8,
    start: Int,
    end: Int,
):
    kinds[count] = kind
    starts[count] = Int64(start)
    ends[count] = Int64(end)


def scan_string(src: BPtr, n: Int, start: Int) -> Int:
    var i = start + 1
    while i < n:
        if i + W <= n:
            var v = src.load[width=W](i)
            var special = (
                v.lt(SIMD[DType.uint8, W](32))
                | v.eq(SIMD[DType.uint8, W](34))
                | v.eq(SIMD[DType.uint8, W](92))
            ).reduce_or()
            if not special:
                i += W
                continue
        var c = src[i]
        if c == 34:
            return i + 1
        if c < 32:
            return -(i + 1)
        if c == 92:
            i += 1
            if i >= n:
                return -(i + 1)
            c = src[i]
            if c == 117:
                if i + 4 >= n:
                    return -(i + 1)
                for j in range(1, 5):
                    if not is_hex(src[i + j]):
                        return -(i + j + 1)
                i += 4
            elif not (
                c == 34
                or c == 92
                or c == 47
                or c == 98
                or c == 102
                or c == 110
                or c == 114
                or c == 116
            ):
                return -(i + 1)
        i += 1
    return -(n + 1)


def scan_number(src: BPtr, n: Int, start: Int) -> Int:
    var i = start
    if src[i] == 45:
        i += 1
        if i >= n:
            return -(i + 1)
    if src[i] == 48:
        i += 1
        if i < n and is_digit(src[i]):
            return -(i + 1)
    elif src[i] >= 49 and src[i] <= 57:
        i += 1
        while i < n and is_digit(src[i]):
            i += 1
    else:
        return -(i + 1)
    if i < n and src[i] == 46:
        i += 1
        if i >= n or not is_digit(src[i]):
            return -(i + 1)
        while i < n and is_digit(src[i]):
            i += 1
    if i < n and (src[i] == 101 or src[i] == 69):
        i += 1
        if i < n and (src[i] == 43 or src[i] == 45):
            i += 1
        if i >= n or not is_digit(src[i]):
            return -(i + 1)
        while i < n and is_digit(src[i]):
            i += 1
    return i


def matches(
    src: BPtr,
    n: Int,
    start: Int,
    a: UInt8,
    b: UInt8,
    c: UInt8,
    d: UInt8,
    length: Int,
) -> Bool:
    if start + length > n:
        return False
    if src[start] != a or src[start + 1] != b or src[start + 2] != c:
        return False
    return length == 3 or src[start + 3] == d


@export("morj_tokenize")
def morj_tokenize(
    src_addr: Int,
    n: Int,
    kinds_addr: Int,
    starts_addr: Int,
    ends_addr: Int,
    capacity: Int,
) abi("C") -> Int:
    if (
        n < 0
        or capacity < n
        or src_addr == 0
        or kinds_addr == 0
        or starts_addr == 0
        or ends_addr == 0
    ):
        return -1
    var src = BPtr(unsafe_from_address=src_addr)
    var kinds = BPtr(unsafe_from_address=kinds_addr)
    var starts = IPtr(unsafe_from_address=starts_addr)
    var ends = IPtr(unsafe_from_address=ends_addr)
    var i = 0
    var count = 0
    while i < n:
        var c = src[i]
        if is_ws(c):
            i += 1
            continue
        if c == 34:
            var end = scan_string(src, n, i)
            if end < 0:
                return end
            emit(kinds, starts, ends, count, UInt8(7), i, end)
            count += 1
            i = end
        elif c == 123:
            emit(kinds, starts, ends, count, UInt8(1), i, i + 1)
            count += 1
            i += 1
        elif c == 125:
            emit(kinds, starts, ends, count, UInt8(2), i, i + 1)
            count += 1
            i += 1
        elif c == 91:
            emit(kinds, starts, ends, count, UInt8(3), i, i + 1)
            count += 1
            i += 1
        elif c == 93:
            emit(kinds, starts, ends, count, UInt8(4), i, i + 1)
            count += 1
            i += 1
        elif c == 44:
            emit(kinds, starts, ends, count, UInt8(5), i, i + 1)
            count += 1
            i += 1
        elif c == 58:
            emit(kinds, starts, ends, count, UInt8(6), i, i + 1)
            count += 1
            i += 1
        elif c == 45 or is_digit(c):
            var end = scan_number(src, n, i)
            if end < 0:
                return end
            emit(kinds, starts, ends, count, UInt8(8), i, end)
            count += 1
            i = end
        elif c == 116 and matches(
            src, n, i, UInt8(116), UInt8(114), UInt8(117), UInt8(101), 4
        ):
            emit(kinds, starts, ends, count, UInt8(9), i, i + 4)
            count += 1
            i += 4
        elif c == 102 and matches(
            src, n, i, UInt8(102), UInt8(97), UInt8(108), UInt8(115), 4
        ):
            if i + 5 > n or src[i + 4] != 101:
                return -(i + 1)
            emit(kinds, starts, ends, count, UInt8(10), i, i + 5)
            count += 1
            i += 5
        elif c == 110 and matches(
            src, n, i, UInt8(110), UInt8(117), UInt8(108), UInt8(108), 4
        ):
            emit(kinds, starts, ends, count, UInt8(11), i, i + 4)
            count += 1
            i += 4
        else:
            return -(i + 1)
    return count


def read_length(src: BPtr, pos: Int) -> Int:
    var value = Int(0)
    for j in range(8):
        value |= Int(src[pos + j]) << (j * 8)
    return value


def write_indent(dst: BPtr, pos: Int, depth: Int) -> Int:
    var p = pos
    dst[p] = UInt8(10)
    p += 1
    for _ in range(depth * 2):
        dst[p] = UInt8(32)
        p += 1
    return p


def string_size(src: BPtr, start: Int, length: Int) -> Int:
    var size = 2
    var i = 0
    while i + W <= length:
        var v = src.load[width=W](start + i)
        var special = (
            v.lt(SIMD[DType.uint8, W](32))
            | v.eq(SIMD[DType.uint8, W](34))
            | v.eq(SIMD[DType.uint8, W](92))
        ).reduce_or()
        if special:
            break
        size += W
        i += W
    while i < length:
        var c = src[start + i]
        if (
            c == 34
            or c == 92
            or c == 8
            or c == 9
            or c == 10
            or c == 12
            or c == 13
        ):
            size += 2
        elif c < 32:
            size += 6
        else:
            size += 1
        i += 1
    return size


def write_string(
    src: BPtr, start: Int, length: Int, dst: BPtr, pos: Int
) -> Int:
    var p = pos
    dst[p] = UInt8(34)
    p += 1
    var i = 0
    while i + W <= length:
        var v = src.load[width=W](start + i)
        var special = (
            v.lt(SIMD[DType.uint8, W](32))
            | v.eq(SIMD[DType.uint8, W](34))
            | v.eq(SIMD[DType.uint8, W](92))
        ).reduce_or()
        if special:
            break
        dst.store(p, v)
        p += W
        i += W
    while i < length:
        var c = src[start + i]
        if c == 34 or c == 92:
            dst[p] = UInt8(92)
            dst[p + 1] = c
            p += 2
        elif c == 8:
            dst[p] = UInt8(92)
            dst[p + 1] = UInt8(98)
            p += 2
        elif c == 9:
            dst[p] = UInt8(92)
            dst[p + 1] = UInt8(116)
            p += 2
        elif c == 10:
            dst[p] = UInt8(92)
            dst[p + 1] = UInt8(110)
            p += 2
        elif c == 12:
            dst[p] = UInt8(92)
            dst[p + 1] = UInt8(102)
            p += 2
        elif c == 13:
            dst[p] = UInt8(92)
            dst[p + 1] = UInt8(114)
            p += 2
        elif c < 32:
            comptime HEX = String("0123456789abcdef")
            var table = HEX.unsafe_ptr()
            dst[p] = UInt8(92)
            dst[p + 1] = UInt8(117)
            dst[p + 2] = UInt8(48)
            dst[p + 3] = UInt8(48)
            dst[p + 4] = table[Int(c) >> 4]
            dst[p + 5] = table[Int(c) & 15]
            p += 6
        else:
            dst[p] = c
            p += 1
        i += 1
    dst[p] = UInt8(34)
    return p + 1


@export("morj_serialized_size")
def morj_serialized_size(ir_addr: Int, n: Int, indent: Int) abi("C") -> Int:
    if n <= 0 or ir_addr == 0:
        return -1
    var src = BPtr(unsafe_from_address=ir_addr)
    var i = 0
    var size = 0
    var depth = 0
    var last_op = UInt8(0)
    while i < n:
        var op = src[i]
        i += 1
        if op == 1 or op == 3:
            if indent != 0 and (last_op == 1 or last_op == 3):
                size += 1 + depth * 2
            size += 1
            depth += 1
        elif op == 2 or op == 4:
            depth -= 1
            if depth < 0:
                return -1
            if indent != 0 and (
                (op == 2 and last_op != 1) or (op == 4 and last_op != 3)
            ):
                size += 1 + depth * 2
            size += 1
        elif op == 5:
            size += 1
            if indent != 0:
                size += 1 + depth * 2
        elif op == 6:
            size += 1 + Int(indent != 0)
        elif op == 7 or op == 8:
            if i + 8 > n:
                return -1
            var length = read_length(src, i)
            i += 8
            if length < 0 or length > n - i:
                return -1
            if indent != 0 and (last_op == 1 or last_op == 3):
                size += 1 + depth * 2
            if op == 7:
                size += string_size(src, i, length)
            else:
                size += length
            i += length
        elif op < 1 or op > 8:
            return -1
        last_op = op
    if depth != 0:
        return -1
    return size


@export("morj_serialize")
def morj_serialize(
    ir_addr: Int, n: Int, dst_addr: Int, dst_capacity: Int, indent: Int
) abi("C") -> Int:
    var expected = morj_serialized_size(ir_addr, n, indent)
    if expected < 0 or dst_capacity < expected or dst_addr == 0:
        return -1
    var src = BPtr(unsafe_from_address=ir_addr)
    var dst = BPtr(unsafe_from_address=dst_addr)
    var i = 0
    var p = 0
    var depth = 0
    var last_op = UInt8(0)
    while i < n:
        var op = src[i]
        i += 1
        if op == 1:
            if indent != 0 and (last_op == 1 or last_op == 3):
                p = write_indent(dst, p, depth)
            dst[p] = UInt8(123)
            p += 1
            depth += 1
        elif op == 2:
            depth -= 1
            if indent != 0 and last_op != 1:
                p = write_indent(dst, p, depth)
            dst[p] = UInt8(125)
            p += 1
        elif op == 3:
            if indent != 0 and (last_op == 1 or last_op == 3):
                p = write_indent(dst, p, depth)
            dst[p] = UInt8(91)
            p += 1
            depth += 1
        elif op == 4:
            depth -= 1
            if indent != 0 and last_op != 3:
                p = write_indent(dst, p, depth)
            dst[p] = UInt8(93)
            p += 1
        elif op == 5:
            dst[p] = UInt8(44)
            p += 1
            if indent != 0:
                p = write_indent(dst, p, depth)
        elif op == 6:
            dst[p] = UInt8(58)
            p += 1
            if indent != 0:
                dst[p] = UInt8(32)
                p += 1
        elif op == 7 or op == 8:
            var length = read_length(src, i)
            i += 8
            if indent != 0 and (last_op == 1 or last_op == 3):
                p = write_indent(dst, p, depth)
            if op == 7:
                p = write_string(src, i, length, dst, p)
            else:
                var j = 0
                while j + W <= length:
                    dst.store(p + j, src.load[width=W](i + j))
                    j += W
                while j < length:
                    dst[p + j] = src[i + j]
                    j += 1
                p += length
            i += length
        last_op = op
    return p
