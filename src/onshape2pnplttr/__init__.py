"""onshape2pnplttr -- convert vector CAD / OnShape drawing PDFs to ``.pnplttr``.

Typical use::

    from onshape2pnplttr import ConvertOptions, convert_pdf, write_document

    result = convert_pdf("Drawing.pdf", ConvertOptions())
    write_document(result.document, "Drawing.pnplttr")
"""
from .config import (
    DEFAULT_WORKSPACE,
    ELEMENT_MODES,
    FIT_MODES,
    PAGE_PRESETS,
    ROTATE_CHOICES,
    WORKSPACE_PRESETS,
    ConvertOptions,
)
from .convert import ConversionResult, ConversionStats, convert_bytes, convert_pdf
from .pnplttr import write_document

__version__ = "0.1.0"

__all__ = [
    "ConvertOptions",
    "ConversionResult",
    "ConversionStats",
    "convert_pdf",
    "convert_bytes",
    "write_document",
    "WORKSPACE_PRESETS",
    "PAGE_PRESETS",
    "DEFAULT_WORKSPACE",
    "FIT_MODES",
    "ROTATE_CHOICES",
    "ELEMENT_MODES",
    "__version__",
]