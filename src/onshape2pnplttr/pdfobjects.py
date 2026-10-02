"""Recursive parser for PDF objects built on top of :mod:`content`.

Turns a token stream into plain Python values:

======================  ==========================
PDF                     Python
======================  ==========================
number                  ``float``
``/Name``               ``str`` (leading slash kept)
``(string)`` / ``<hex>``  ``bytes``
``[ ... ]``             ``list``
``<< ... >>``           ``dict``
``N G R``               :class:`Ref`
``true`` / ``false``    ``bool``
``null``                ``None``
======================  ==========================
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from .content import Token, tokenize

_OBJ_HEADER = re.compile(rb"(?<![\d])(\d+)\s+(\d+)\s+obj\b")
_STREAM_START = re.compile(rb"\bstream\r?\n")


@dataclass(frozen=True)
class Ref:
    """An indirect object reference such as ``12 0 R``."""

    number: int
    generation: int = 0

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.number} {self.generation} R"


class ParseError(ValueError):
    pass


class Parser:
    def __init__(self, data: bytes) -> None:
        self._tokens: list[Token] = list(tokenize(data))
        self._i = 0

    # -- token helpers ---------------------------------------------------
    def _peek(self, offset: int = 0) -> Token | None:
        idx = self._i + offset
        if idx < len(self._tokens):
            return self._tokens[idx]
        return None

    def _next(self) -> Token:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input")
        self._i += 1
        return tok

    def at_end(self) -> bool:
        return self._i >= len(self._tokens)

    # -- grammar ---------------------------------------------------------
    def parse_value(self) -> object:
        tok = self._peek()
        if tok is None:
            raise ParseError("unexpected end of input")
        kind = tok.kind
        if kind == "num":
            return self._parse_number_or_ref()
        if kind == "name":
            return self._next().value
        if kind in ("str", "hex"):
            return self._next().value
        if kind == "[":
            return self._parse_array()
        if kind == "<<":
            return self._parse_dict()
        if kind == "op":
            kw = self._next().value
            if kw == "true":
                return True
            if kw == "false":
                return False
            if kw == "null":
                return None
            raise ParseError(f"unexpected keyword {kw!r}")
        raise ParseError(f"unexpected token {tok!r}")

    def _parse_number_or_ref(self) -> object:
        # A reference looks like  <int> <int> R
        a, b, c = self._peek(0), self._peek(1), self._peek(2)
        if (
            a is not None and a.kind == "num"
            and b is not None and b.kind == "num"
            and c is not None and c.kind == "op" and c.value == "R"
        ):
            number = int(self._next().value)
            generation = int(self._next().value)
            self._next()  # consume R
            return Ref(number, generation)
        return self._next().value

    def _parse_array(self) -> list:
        self._next()  # [
        items: list = []
        while True:
            tok = self._peek()
            if tok is None:
                raise ParseError("unterminated array")
            if tok.kind == "]":
                self._next()
                return items
            items.append(self.parse_value())

    def _parse_dict(self) -> dict:
        self._next()  # <<
        result: dict = {}
        while True:
            tok = self._peek()
            if tok is None:
                raise ParseError("unterminated dictionary")
            if tok.kind == ">>":
                self._next()
                return result
            key = self._next()
            if key.kind != "name":
                raise ParseError(f"dictionary key must be a name, got {key!r}")
            result[key.value] = self.parse_value()

    def parse_until_end(self) -> list:
        out: list = []
        while not self.at_end():
            out.append(self.parse_value())
        return out


def parse(data: bytes) -> object:
    """Parse a standalone object body (no ``obj``/``endobj`` wrapper)."""
    return Parser(data).parse_value()


def _find_object_end(data: bytes, start: int) -> int:
    """Locate the ``endobj`` closing the object that begins at *start*.

    If the object carries a stream, the search resumes after ``endstream`` so
    that an incidental ``endobj`` inside the (possibly binary) payload cannot
    truncate the object.
    """
    endobj = data.find(b"endobj", start)
    if endobj < 0:
        return -1
    match = _STREAM_START.search(data, start, endobj)
    if match:
        endstream = data.find(b"endstream", match.end())
        if endstream >= 0:
            after = data.find(b"endobj", endstream)
            if after >= 0:
                return after
    return endobj


def iter_objects(data: bytes) -> Iterator[tuple[int, int, bytes]]:
    """Yield ``(number, generation, body)`` for each ``N G obj ... endobj``.

    Scanning advances past each ``endobj`` so tokens that merely *look* like an
    object header inside a stream payload are not misinterpreted.
    """
    pos = 0
    n = len(data)
    while pos < n:
        m = _OBJ_HEADER.search(data, pos)
        if not m:
            return
        number, generation = int(m.group(1)), int(m.group(2))
        body_start = m.end()
        end = _find_object_end(data, body_start)
        if end < 0:
            return
        yield number, generation, data[body_start:end]
        pos = end + len(b"endobj")