"""onshape2pnplttr -- CAD drawing PDFs in, plotter-clean ``.pnplttr`` out.

Two tools:

``onshape2pnplttr``
    Convert a vector CAD / OnShape drawing PDF into a ``.pnplttr`` document::

        from onshape2pnplttr import ConvertOptions, convert_pdf, write_document

        result = convert_pdf("Drawing.pdf", ConvertOptions())
        write_document(result.document, "Drawing.pnplttr")

``pnplttr-clean``
    Tidy a generated document -- drop the detail a pen cannot draw::

        from onshape2pnplttr import CleanOptions, clean_document, clean_file

        clean_file("Drawing.pnplttr", "Clean.pnplttr", CleanOptions())
"""
from .clean import (
    DEFAULT_EPSILON_MM,
    DEFAULT_MIN_EXTENT_MM,
    DEFAULT_MIN_DETAIL_MM,
    DEFAULT_SIMPLIFY_MM,
    CleanOptions,
    CleanResult,
    CleanStats,
    clean_document,
    clean_file,
)
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
from .merge import DEFAULT_TOLERANCE_MM, merge_polylines
from .pnplttr import write_document

__version__ = "0.1.0"

__all__ = [
    "ConvertOptions",
    "ConversionResult",
    "ConversionStats",
    "convert_pdf",
    "convert_bytes",
    "CleanOptions",
    "CleanResult",
    "CleanStats",
    "clean_document",
    "clean_file",
    "merge_polylines",
    "write_document",
    "WORKSPACE_PRESETS",
    "PAGE_PRESETS",
    "DEFAULT_WORKSPACE",
    "DEFAULT_TOLERANCE_MM",
    "DEFAULT_EPSILON_MM",
    "DEFAULT_MIN_DETAIL_MM",
    "DEFAULT_MIN_EXTENT_MM",
    "DEFAULT_SIMPLIFY_MM",
    "FIT_MODES",
    "ROTATE_CHOICES",
    "ELEMENT_MODES",
    "__version__",
]