"""PDF -> ``.pnplttr`` conversion pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path as _FsPath

from . import pnplttr
from .config import PT_TO_MM, ConvertOptions
from .geometry import Bounds
from .interpreter import Interpreter
from .model import Path, PathKind, Subpath
from .pdf import PdfDocument


@dataclass
class ConversionStats:
    source_layers: dict[str, int] = field(default_factory=dict)
    used_layers: list[str] = field(default_factory=list)
    elements: int = 0
    points: int = 0
    subpaths: int = 0
    natural_mm: tuple[float, float] = (0.0, 0.0)
    scale: float = 1.0
    page_mm: tuple[float, float] = (0.0, 0.0)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ConversionResult:
    document: dict
    stats: ConversionStats


def convert_pdf(source: str | _FsPath, options: ConvertOptions | None = None) -> ConversionResult:
    data = _FsPath(source).read_bytes()
    return convert_bytes(data, options)


def convert_bytes(data: bytes, options: ConvertOptions | None = None) -> ConversionResult:
    options = options or ConvertOptions()
    pdf = PdfDocument(data)
    pages = pdf.pages()
    if not pages:
        raise ValueError("no /Page objects found; not a supported PDF")
    if options.page_index >= len(pages):
        raise ValueError(f"page_index {options.page_index} out of range ({len(pages)} pages)")
    page = pages[options.page_index]

    layer_names = pdf.layer_names(page)
    default_layer = next(iter(layer_names.values()), "Default")
    content = pdf.page_content(page)

    interpreter = Interpreter(layer_names=layer_names, default_layer=default_layer)
    paths = interpreter.run(content)

    return _build_document(paths, options)
def _compute_layout(
    natural_w_mm: float, natural_h_mm: float, options: ConvertOptions
) -> tuple[float, float, float]:
    """Return ``(scale, page_width_mm, page_height_mm)`` for the drawing."""
    ws_w, ws_h = options.workspace
    usable_w = ws_w * (1.0 - 2.0 * options.margin)
    usable_h = ws_h * (1.0 - 2.0 * options.margin)

    if options.fit == "fit":
        if natural_w_mm > 0 and natural_h_mm > 0:
            scale = min(usable_w / natural_w_mm, usable_h / natural_h_mm)
        else:
            scale = 1.0
    elif options.fit == "actual":
        scale = 1.0
    else:  # "scale"
        scale = options.scale

    page_w = natural_w_mm * scale
    page_h = natural_h_mm * scale
    if options.page is not None:
        page_w, page_h = options.page
    return scale, page_w, page_h


def _build_document(paths: list[Path], options: ConvertOptions) -> ConversionResult:
    stats = ConversionStats()

    # -- filter painted paths -------------------------------------------
    kept: list[Path] = []
    for path in paths:
        if path.kind is PathKind.FILL and not options.include_fills:
            continue
        if path.layer in options.drop_layers:
            continue
        kept.append(path)

    entries: list[tuple[str, Subpath]] = []
    for path in kept:
        stats.source_layers[path.layer] = stats.source_layers.get(path.layer, 0) + len(path.subpaths)
        for subpath in path.subpaths:
            if subpath.moves:
                entries.append((path.layer, subpath))
    stats.subpaths = len(entries)

    # -- natural size (flattened so the box matches the plotted geometry) -
    bounds = Bounds()
    for _, subpath in entries:
        bounds.add_points(subpath.polyline(curves=True, segments=options.bezier_segments))
    natural_w_mm = bounds.width * PT_TO_MM
    natural_h_mm = bounds.height * PT_TO_MM
    stats.natural_mm = (natural_w_mm, natural_h_mm)

    scale, page_w, page_h = _compute_layout(natural_w_mm, natural_h_mm, options)
    stats.scale = scale
    stats.page_mm = (page_w, page_h)

    draw_w = natural_w_mm * scale
    draw_h = natural_h_mm * scale
    offset_x = (page_w - draw_w) / 2.0
    offset_y = (page_h - draw_h) / 2.0

    def transform(x_pt: float, y_pt: float) -> tuple[float, float]:
        # device pt (y-up) -> document mm (y-down), anchored to the artwork box.
        x = offset_x + (x_pt - bounds.min_x) * PT_TO_MM * scale
        y = offset_y + (bounds.max_y - y_pt) * PT_TO_MM * scale
        return (round(x, options.round_mm), round(y, options.round_mm))

    # -- pens (first-seen layer order) ----------------------------------
    layer_order: list[str] = []
    for path in kept:
        if path.layer not in layer_order:
            layer_order.append(path.layer)
    pen_index = {name: i for i, name in enumerate(layer_order)}
    pens = [
        pnplttr.make_pen(name, options.layer_colors.get(name, options.pen_color), options.pen_width_mm)
        for name in layer_order
    ]
    stats.used_layers = list(layer_order)

    # -- elements --------------------------------------------------------
    elements: list[dict] = []
    for index, (layer, subpath) in enumerate(entries):
        element_id = f"e{index + 1}"
        pen = pen_index.get(layer, 0)
        if options.element_mode == "path":
            strokes = [pnplttr.subpath_to_stroke(subpath, transform)]
            elements.append(pnplttr.path_element(element_id, pen, index, strokes))
        else:
            points = [
                transform(x, y)
                for x, y in subpath.polyline(curves=True, segments=options.bezier_segments)
            ]
            elements.append(pnplttr.drawing_element(element_id, pen, index, points))
            stats.points += len(points)

    ws_w, ws_h = options.workspace
    if draw_w > ws_w + 1e-6 or draw_h > ws_h + 1e-6:
        stats.warnings.append(
            f"artwork {draw_w:.2f}x{draw_h:.2f} mm exceeds workspace {ws_w:.0f}x{ws_h:.0f} mm"
        )
    if not pens:
        pens = [pnplttr.make_pen("Pen 1", options.pen_color, options.pen_width_mm)]
        stats.warnings.append("no drawable geometry found; wrote an empty document")

    document = {
        "meta": pnplttr.make_meta(),
        "page": pnplttr.make_page(page_w, page_h, ws_w, ws_h),
        "pens": pens,
        "elements": elements,
    }
    stats.elements = len(elements)
    return ConversionResult(document, stats)