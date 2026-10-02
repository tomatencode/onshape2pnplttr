"""A tokenizer for PDF content streams.

This is deliberately independent of the higher-level object parser: a content
stream is a sequence of operands followed by an operator, and the tokenizer
only has to recognise the primitive token shapes.
"""
from __future__ import annotations

from typing import Iterator, NamedTuple

WHITESPACE = b" \t\r\n\x0c\x00"
DELIMITERS = b"()<>[]{}/%"

_SIMPLE_ESCAPES = {0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09, 0x62: 0x08, 0x66: 0x0C}


class Token(NamedTuple):
    kind: str  # "num" | "name" | "str" | "hex" | "op" | "[" | "]" | "<<" | ">>"
    value: object


def decode_name(raw: str) -> str:
    """Decode a PDF name token (``/A#20B`` -> ``/A B``)."""
    if "#" not in raw:
        return raw
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "#" and i + 2 < len(raw):
            try:
                out.append(int(raw[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out.append(ord(ch))
        i += 1
    return out.decode("latin1")


def _read_string(data: bytes, i: int) -> tuple[bytes, int]:
    """Read a literal ``( ... )`` string starting at *i* (the open paren)."""
    buf = bytearray()
    depth = 1
    i += 1
    n = len(data)
    while i < n and depth:
        ch = data[i]
        if ch == 0x5C:  # backslash
            i += 1
            if i >= n:
                break
            esc = data[i]
            if esc in _SIMPLE_ESCAPES:
                buf.append(_SIMPLE_ESCAPES[esc])
                i += 1
            elif 0x30 <= esc <= 0x37:  # octal, up to 3 digits
                digits = bytearray()
                while i < n and len(digits) < 3 and 0x30 <= data[i] <= 0x37:
                    digits.append(data[i])
                    i += 1
                buf.append(int(digits, 8) & 0xFF)
            elif esc in (0x0A, 0x0D):  # line continuation
                i += 1
                if esc == 0x0D and i < n and data[i] == 0x0A:
                    i += 1
            else:
                buf.append(esc)
                i += 1
            continue
        if ch == 0x28:  # (
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == 0x29:  # )
            depth -= 1
            i += 1
            if depth == 0:
                break
            buf.append(ch)
            continue
        buf.append(ch)
        i += 1
    return bytes(buf), i


def tokenize(data: bytes) -> Iterator[Token]:
    """Yield tokens from a PDF content stream or object body."""
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c in WHITESPACE:
            i += 1
            continue
        if c == 0x25:  # % comment to end of line
            j = data.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == 0x2F:  # /Name
            j = i + 1
            while j < n and data[j] not in WHITESPACE and data[j] not in DELIMITERS:
                j += 1
            yield Token("name", decode_name(data[i:j].decode("latin1")))
            i = j
            continue
        if c == 0x28:  # (literal string)
            value, i = _read_string(data, i)
            yield Token("str", value)
            continue
        if c == 0x3C:  # <
            if i + 1 < n and data[i + 1] == 0x3C:
                yield Token("<<", None)
                i += 2
                continue
            j = data.find(b">", i + 1)
            if j < 0:
                j = n
            hx = bytes(b for b in data[i + 1:j] if b not in WHITESPACE)
            yield Token("hex", hx)
            i = j + 1
            continue
        if c == 0x3E:  # >
            if i + 1 < n and data[i + 1] == 0x3E:
                yield Token(">>", None)
                i += 2
                continue
            i += 1
            continue
        if c in b"[]":
            yield Token(chr(c), None)
            i += 1
            continue
        if c in b"+-.0123456789":
            j = i
            while j < n and data[j] in b"+-.0123456789eE":
                j += 1
            try:
                yield Token("num", float(data[i:j]))
            except ValueError:
                yield Token("op", data[i:j].decode("latin1"))
            i = j
            continue
        # operator / keyword
        j = i
        while j < n and data[j] not in WHITESPACE and data[j] not in DELIMITERS:
            j += 1
        if j == i:
            i += 1
            continue
        yield Token("op", data[i:j].decode("latin1"))
        i = j
