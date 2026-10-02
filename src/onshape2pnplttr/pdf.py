"""High-level reader for the subset of PDF the converter needs.

Deliberately dependency-free: it understands classic (non-object-stream)
PDFs, indirect references, Flate streams and Optional Content Groups -- which
covers typical OnShape / ODA / CAD technical-drawing exports.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from .pdfobjects import Parser, Ref, iter_objects

_STREAM_RE = re.compile(rb"stream\r?\n")


def decode_pdf_text(raw: bytes) -> str:
    """Decode a PDF text string (handles UTF-16 BOMs and UTF-8 BOM)."""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", "replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", "replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace")
    return raw.decode("latin1")


@dataclass
class PdfObject:
    number: int
    generation: int
    value: object
    stream: bytes | None


class PdfDocument:
    """Parses a PDF file into indirect objects and answers structural queries."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._objects: dict[int, PdfObject] = {}
        self._parse_objects()

    # -- construction ----------------------------------------------------
    def _parse_objects(self) -> None:
        for number, generation, body in iter_objects(self._data):
            match = _STREAM_RE.search(body)
            stream: bytes | None = None
            if match:
                end = body.rfind(b"endstream")
                raw = body[match.end():end] if end >= 0 else body[match.end():]
                if raw.endswith(b"\r\n"):
                    raw = raw[:-2]
                elif raw.endswith((b"\n", b"\r")):
                    raw = raw[:-1]
                stream = raw
                dict_bytes = body[:match.start()]
            else:
                dict_bytes = body
            try:
                value = Parser(dict_bytes).parse_value()
            except Exception:
                value = None
            self._objects[number] = PdfObject(number, generation, value, stream)

    # -- accessors -------------------------------------------------------
    def object(self, number: int) -> PdfObject | None:
        return self._objects.get(number)

    def resolve(self, value: object) -> object:
        """Follow an indirect reference (once) if *value* is one."""
        if isinstance(value, Ref):
            obj = self._objects.get(value.number)
            return obj.value if obj is not None else None
        return value

    def inherited(self, node: dict, key: str) -> object:
        """Look up *key* on *node*, walking ``/Parent`` ancestors if needed.

        PDF page attributes such as ``/Resources`` and ``/MediaBox`` are
        inheritable, and CAD exporters routinely place them on the ``/Pages``
        node rather than on each page.
        """
        current: object = node
        for _ in range(64):  # guard against reference cycles
            if not isinstance(current, dict):
                return None
            if key in current:
                return self.resolve(current[key])
            current = self.resolve(current.get("/Parent"))
        return None

    def stream_bytes(self, value: object) -> bytes:
        """Return the decoded stream payload referenced by *value*."""
        number = value.number if isinstance(value, Ref) else int(value)  # type: ignore[arg-type]
        obj = self._objects.get(number)
        if obj is None or obj.stream is None:
            return b""
        return self._decode(obj)

    def _decode(self, obj: PdfObject) -> bytes:
        data = obj.stream or b""
        info = obj.value if isinstance(obj.value, dict) else {}
        filters = info.get("/Filter")
        if filters is None:
            return data
        if isinstance(filters, str):
            filters = [filters]
        for name in filters:
            if name == "/FlateDecode":
                data = zlib.decompress(data)
            elif name == "/ASCIIHexDecode":
                data = _ascii_hex_decode(data)
            else:  # pragma: no cover - unsupported filter, pass through
                break
        return data

    # -- structure -------------------------------------------------------
    def pages(self) -> list[dict]:
        return [
            obj.value
            for obj in self._objects.values()
            if isinstance(obj.value, dict) and obj.value.get("/Type") == "/Page"
        ]

    def page_media_box(self, page: dict) -> tuple[float, float]:
        box = self.inherited(page, "/MediaBox")
        if isinstance(box, list) and len(box) == 4:
            x0, y0, x1, y1 = (float(v) for v in box)
            return (abs(x1 - x0), abs(y1 - y0))
        return (0.0, 0.0)

    def page_content(self, page: dict) -> bytes:
        contents = page.get("/Contents")
        refs = contents if isinstance(contents, list) else [contents]
        parts = [self.stream_bytes(r) for r in refs if r is not None]
        return b"\n".join(p for p in parts if p)

    def layer_names(self, page: dict) -> dict[str, str]:
        """Map marked-content property names (``/OC0``) to layer names.

        The mapping lives in ``/Resources /Properties`` and each target OCG
        object carries a human-readable ``/Name``. Falls back to the raw
        property name when no OCG is found.
        """
        resources = self.inherited(page, "/Resources")
        names: dict[str, str] = {}
        if not isinstance(resources, dict):
            return names
        properties = self.resolve(resources.get("/Properties"))
        if not isinstance(properties, dict):
            return names
        for prop, ref in properties.items():
            ocg = self.resolve(ref)
            name = prop.lstrip("/")
            if isinstance(ocg, dict):
                raw = ocg.get("/Name")
                if isinstance(raw, bytes):
                    name = decode_pdf_text(raw)
                elif isinstance(raw, str):
                    name = raw.lstrip("/")
            names[prop] = name
        return names


def _ascii_hex_decode(data: bytes) -> bytes:  # pragma: no cover - rare in CAD exports
    cleaned = bytes(b for b in data if b not in b" \t\r\n\x0c")
    if cleaned.endswith(b">"):
        cleaned = cleaned[:-1]
    if len(cleaned) % 2:
        cleaned += b"0"
    return bytes.fromhex(cleaned.decode("ascii"))