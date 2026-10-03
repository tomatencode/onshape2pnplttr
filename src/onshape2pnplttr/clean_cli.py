"""Command-line interface for the ``.pnplttr`` cleaner.

    pnplttr-clean Drawing.pnplttr -o Clean.pnplttr
    pnplttr-clean Drawing.pnplttr --min-detail 0.3 --tolerance 0.1
    pnplttr-clean Drawing.pnplttr --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .clean import (
    DEFAULT_EPSILON_MM,
    DEFAULT_MIN_EXTENT_MM,
    DEFAULT_MIN_DETAIL_MM,
    DEFAULT_QUANTISE_MM,
    DEFAULT_SIMPLIFY_MM,
    PATH_MODES,
    CleanOptions,
    CleanResult,
    clean_document,
)
from .pnplttr import write_document


def _percent(before: float, after: float) -> str:
    if not before:
        return "  0.0%"
    return f"{100.0 * (before - after) / before:5.1f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pnplttr-clean",
        description="Remove geometry a pen cannot draw from a .pnplttr file: short edges, "
                    "invisible detail and whole elements below the pen width.",
    )
    parser.add_argument("input", help="source .pnplttr document")
    parser.add_argument("-o", "--output", metavar="PATH",
                        help="output path (default: INPUT.clean.pnplttr)")
    parser.add_argument("--min-detail", type=float, default=DEFAULT_MIN_DETAIL_MM, metavar="MM",
                        help="drop points whose removal moves the stroke less than MM, which "
                             "is what removes short edges, staircases and spurs "
                             "(default: %(default)s, 0 disables)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_SIMPLIFY_MM, metavar="MM",
                        help="Douglas-Peucker tolerance in MM (default: %(default)s, 0 disables)")
    parser.add_argument("--min-extent", type=float, default=DEFAULT_MIN_EXTENT_MM, metavar="MM",
                        help="drop elements smaller than this bounding box in MM "
                             "(default: %(default)s, 0 disables)")
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON_MM, metavar="MM",
                        help="points closer than MM count as the same spot "
                             "(default: %(default)s)")
    parser.add_argument("--dedupe-segments", action="store_true",
                        help="also drop ink another element already drew (lightens overlaps)")
    parser.add_argument("--quantise", type=float, default=DEFAULT_QUANTISE_MM, metavar="MM",
                        help="coordinate quantum for --dedupe-segments (default: %(default)s)")
    parser.add_argument("--path-mode", choices=list(PATH_MODES), default="skip",
                        help="'skip' leaves Path elements alone, 'flatten' turns them into "
                             "Drawing polylines first (default: %(default)s)")
    parser.add_argument("--bezier-segments", type=int, default=16,
                        help="curve flattening resolution for --path-mode flatten")
    parser.add_argument("--protect-pen", type=int, action="append", default=[], metavar="N",
                        help="leave elements of pen N untouched (repeatable)")
    parser.add_argument("--in-place", action="store_true",
                        help="overwrite the input file instead of writing a new one")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument("--compact", action="store_true", help="write minified JSON")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress the summary")
    return parser


def _options_from_args(args: argparse.Namespace) -> CleanOptions:
    return CleanOptions(
        min_detail=args.min_detail,
        tolerance=args.tolerance,
        min_extent=args.min_extent,
        epsilon=args.epsilon,
        dedupe_segments=args.dedupe_segments,
        quantise=args.quantise,
        path_mode=args.path_mode,
        bezier_segments=args.bezier_segments,
        protect_pens=tuple(args.protect_pen),
    )


def print_summary(result: CleanResult, options: CleanOptions, output: Path, source: Path) -> None:
    stats = result.stats
    print(f"{source} -> {output}")
    print(f"  elements : {stats.elements_before} -> {stats.elements_after} "
          f"({_percent(stats.elements_before, stats.elements_after)} gone)")
    print(f"  segments : {stats.segments_before} -> {stats.segments_after} "
          f"({_percent(stats.segments_before, stats.segments_after)} gone)")
    print(f"  points   : {stats.points_before} -> {stats.points_after} "
          f"({_percent(stats.points_before, stats.points_after)} gone)")
    print(f"  ink      : {stats.length_before:.0f} -> {stats.length_after:.0f} mm pen-down "
          f"({_percent(stats.length_before, stats.length_after)} less)")
    print(f"  stray    : at most {options.error_bound_mm:.3f} mm per removed point")
    for reason, count in sorted(stats.removed_points.items()):
        print(f"  pass     : {reason:<20} {count} point(s)")
    for reason, count in sorted(stats.dropped_elements.items()):
        print(f"  dropped  : {reason:<20} {count} element(s)")
    if stats.duplicate_segments:
        print(f"  dedupe   : {stats.duplicate_segments} duplicate segment(s)")
    if stats.path_elements:
        print(f"  paths    : {stats.path_elements} Path element(s) "
              f"({'flattened' if options.path_mode == 'flatten' else 'left alone'})")
    if stats.protected:
        print(f"  protected: {stats.protected} element(s) on pen(s) "
              f"{', '.join(str(pen) for pen in options.protect_pens)}")
    for name, before, after in stats.pens:
        print(f"  pen      : {name:<20} {before:>5} -> {after:<5} element(s)")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.input)
    if not source.exists():
        print(f"error: {source} not found", file=sys.stderr)
        return 2
    try:
        options = _options_from_args(args)
        document = json.loads(source.read_text(encoding="utf-8"))
        result = clean_document(document, options)
    except json.JSONDecodeError as exc:
        print(f"error: {source} is not valid JSON ({exc})", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.in_place:
        output = source
    elif args.output:
        output = Path(args.output)
    else:
        output = source.with_suffix(".clean.pnplttr")
    if not args.dry_run:
        write_document(result.document, output, indent=None if args.compact else 2)
    if not args.quiet:
        target = Path(f"{output} (dry run)") if args.dry_run else output
        print_summary(result, options, target, source)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())