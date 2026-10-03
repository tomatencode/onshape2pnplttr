"""Command-line interface.

    onshape2pnplttr Drawing.pdf -o Drawing.pnplttr
    onshape2pnplttr Drawing.pdf --workspace V2 --mode path
    onshape2pnplttr Drawing.pdf --list-layers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_WORKSPACE, PAGE_PRESETS, ROTATE_CHOICES, WORKSPACE_PRESETS, ConvertOptions
from .convert import ConversionResult, convert_pdf
from .pnplttr import write_document


def _parse_size(text: str) -> tuple[float, float]:
    try:
        w, h = text.lower().replace(" ", "").split("x")
        return (float(w), float(h))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected WxH (e.g. 200x285), got {text!r}") from exc


def _parse_layer_color(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"expected LAYER=#RRGGBB, got {text!r}")
    name, color = text.split("=", 1)
    return name.strip(), color.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="onshape2pnplttr",
        description="Convert a vector CAD / OnShape technical-drawing PDF into a PenPlotterApp .pnplttr file.",
    )
    parser.add_argument("input", help="source PDF (vector CAD / OnShape export)")
    parser.add_argument("-o", "--output", help="output .pnplttr path (default: alongside the input)")
    parser.add_argument("--workspace", choices=sorted(WORKSPACE_PRESETS), default=DEFAULT_WORKSPACE,
                        help="plotter workspace preset (default: %(default)s)")
    parser.add_argument("--workspace-size", type=_parse_size, metavar="WxH",
                        help="explicit workspace in mm, overrides --workspace")
    parser.add_argument("--page", choices=sorted(PAGE_PRESETS),
                        help="fix the output page size to a preset (artwork is centred)")
    parser.add_argument("--fit", choices=["fit", "actual", "scale"], default="fit",
                        help="fit to workspace, 1:1 mm, or use --scale (default: %(default)s)")
    parser.add_argument("--scale", type=float, default=1.0, help="scale factor for --fit scale")
    parser.add_argument("--margin", type=float, default=0.02,
                        help="fraction reserved on each side for --fit fit (default: %(default)s)")
    parser.add_argument("--mode", choices=["drawing", "path"], default="drawing", dest="element_mode",
                        help="'drawing' flattens curves; 'path' keeps Béziers (needs app support)")
    parser.add_argument("--bezier-segments", type=int, default=16, help="curve flattening resolution")
    parser.add_argument("--pen-width", type=float, default=0.4, help="default pen width in mm")
    parser.add_argument("--pen-color", default="#000000", help="default pen colour")
    parser.add_argument("--layer-color", type=_parse_layer_color, action="append", default=[],
                        metavar="LAYER=#RRGGBB", help="per-layer pen colour (repeatable)")
    parser.add_argument("--no-fills", action="store_true", help="drop filled regions (keep outlines only)")
    parser.add_argument("--drop-layer", action="append", default=[], metavar="NAME",
                        help="exclude a layer by name (repeatable)")
    parser.add_argument("--page-index", type=int, default=0, help="PDF page to convert (default: 0)")
    parser.add_argument("--rotate", type=int, choices=list(ROTATE_CHOICES), default=90,
                        help="rotate artwork clockwise in degrees (default: %(default)s)")
    parser.add_argument("--list-layers", action="store_true", help="list detected layers and exit")
    parser.add_argument("--compact", action="store_true", help="write minified JSON")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress the summary")
    return parser


def _options_from_args(args: argparse.Namespace) -> ConvertOptions:
    workspace = args.workspace_size or WORKSPACE_PRESETS[args.workspace]
    page = PAGE_PRESETS[args.page] if args.page else None
    return ConvertOptions(
        workspace=workspace,
        margin=args.margin,
        fit=args.fit,
        scale=args.scale,
        page=page,
        element_mode=args.element_mode,
        bezier_segments=args.bezier_segments,
        pen_width_mm=args.pen_width,
        pen_color=args.pen_color,
        layer_colors=dict(args.layer_color),
        include_fills=not args.no_fills,
        drop_layers=tuple(args.drop_layer),
        page_index=args.page_index,
        rotate=args.rotate,
    )


def _print_summary(result: ConversionResult, output: Path, source: Path) -> None:
    stats = result.stats
    print(f"{source} -> {output}")
    print(f"  elements : {stats.elements}   subpaths: {stats.subpaths}   points: {stats.points}")
    print(f"  artwork  : {stats.natural_mm[0]:.2f} x {stats.natural_mm[1]:.2f} mm "
          f"(scale {stats.scale:.4f})")
    print(f"  page     : {stats.page_mm[0]:.2f} x {stats.page_mm[1]:.2f} mm")
    for layer, count in stats.source_layers.items():
        print(f"  layer    : {layer:<20} {count} subpath(s)")
    for warning in stats.warnings:
        print(f"  warning  : {warning}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.input)
    if not source.exists():
        print(f"error: {source} not found", file=sys.stderr)
        return 2
    try:
        options = _options_from_args(args)
        result = convert_pdf(source, options)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.list_layers:
        print(f"layers in {source}:")
        for layer, count in result.stats.source_layers.items():
            print(f"  {layer:<20} {count} subpath(s)")
        return 0

    output = Path(args.output) if args.output else source.with_suffix(".pnplttr")
    write_document(result.document, output, indent=None if args.compact else 2)
    if not args.quiet:
        _print_summary(result, output, source)
    return 0