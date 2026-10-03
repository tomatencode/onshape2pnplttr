"""PDF -> ``.pnplttr`` conversion pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path as _FsPath

from . import pnplttr
from .config import PT_TO_MM, ConvertOptions
from .geometry import Bounds
from .interpreter import Interpreter
from .merge import merge_polylines
from .model import Path, PathKind, Subpath
from .pdf import PdfDocument


@dataclass
class ConversionStats:
    source_layers: dict[str, int] = field(default_factory=dict)
    used_layers: list[str] = field(default_factory=list)
    elements: int = 0
    points: int = 0
    subpaths: int = 0
    merged: int = 0
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
    raw_w_mm = bounds.width * PT_TO_MM
    raw_h_mm = bounds.height * PT_TO_MM
    if options.rotate in (90, 270):
        natural_w_mm, natural_h_mm = raw_h_mm, raw_w_mm
    else:
        natural_w_mm, natural_h_mm = raw_w_mm, raw_h_mm
    stats.natural_mm = (natural_w_mm, natural_h_mm)

    scale, page_w, page_h = _compute_layout(natural_w_mm, natural_h_mm, options)
    stats.scale = scale
    stats.page_mm = (page_w, page_h)

    draw_w = natural_w_mm * scale
    draw_h = natural_h_mm * scale
    offset_x = (page_w - draw_w) / 2.0
    offset_y = (page_h - draw_h) / 2.0

    rotate = options.rotate

    def transform(x_pt: float, y_pt: float) -> tuple[float, float]:
        # device pt (y-up) -> document mm (y-down), anchored to the artwork
        # box, rotated clockwise by ``rotate`` degrees about the box centre.
        # (u, v) is the unrotated top-left-origin position in pt.
        u = x_pt - bounds.min_x
        v = bounds.max_y - y_pt
        if rotate == 90:
            ru = bounds.height - v
            rv = u
        elif rotate == 180:
            ru = bounds.width - u
            rv = bounds.height - v
        elif rotate == 270:
            ru = v
            rv = bounds.width - u
        else:
            ru, rv = u, v
        x = offset_x + ru * PT_TO_MM * scale
        y = offset_y + rv * PT_TO_MM * scale
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

    if options.element_mode == "path":
        # Lossless mode: one element per subpath, Béziers kept as strokes.
        for index, (layer, subpath) in enumerate(entries):
            element_id = f"e{index + 1}"
            pen = pen_index.get(layer, 0)
            strokes = [pnplttr.subpath_to_stroke(subpath, transform)]
            elements.append(pnplttr.path_element(element_id, pen, index, strokes))
    else:
        # Flattened mode: a CAD exporter breaks one visible line across
        # several subpaths (every PDF moveto starts a new one), so join the
        # pieces that touch before emitting, otherwise the plotter lifts the
        # pen at every break. See :mod:`onshape2pnplttr.merge`.
        polylines: list[tuple[str, list[tuple[float, float]]]] = [
            (
                layer,
                [
                    transform(x, y)
                    for x, y in subpath.polyline(curves=True, segments=options.bezier_segments)
                ],
            )
            for layer, subpath in entries
        ]
        stats.points = sum(len(points) for _, points in polylines)

        if options.merge_continuations and len(polylines) > 1:
            merged = merge_polylines(polylines, options.merge_tolerance_mm)
        else:
            merged = polylines
        stats.merged = len(polylines) - len(merged)

        for index, (layer, points) in enumerate(merged):
            element_id = f"e{index + 1}"
            pen = pen_index.get(layer, 0)
            elements.append(pnplttr.drawing_element(element_id, pen, index, points))

    if options.outline and entries:
        # Rectangular outline around the fitted artwork bounds (document space
        # rectangle at the drawn offset), emitted last on the first pen.
        x0 = round(offset_x, options.round_mm)
        y0 = round(offset_y, options.round_mm)
        x1 = round(offset_x + draw_w, options.round_mm)
        y1 = round(offset_y + draw_h, options.round_mm)
        outline_id = f"e{len(elements) + 1}"
        outline_z = len(elements)
        if options.element_mode == "path":
            corner = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            moves = [
                {"type": "Line", "x1": ax, "y1": ay, "x2": bx, "y2": by}
                for (ax, ay), (bx, by) in zip(corner, corner[1:])
            ]
            elements.append(
                pnplttr.path_element(outline_id, 0, outline_z, [{"start": [x0, y0], "moves": moves}])
            )
        else:
            outline_points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            elements.append(pnplttr.drawing_element(outline_id, 0, outline_z, outline_points))
            stats.points += len(outline_points)

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