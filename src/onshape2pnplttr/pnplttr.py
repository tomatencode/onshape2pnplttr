"""Build and write ``.pnplttr`` documents (PenPlotterApp ``doctype_version`` 2).

Schema reference: PenPlotterApp ``src/features/document/types.ts``.

Coordinates are millimetres, y-down. Elements are one of:

* ``Drawing`` -- a flattened polyline (``points``).
* ``Path``    -- lossless strokes for editors that support it (``strokes``).
                Requires the matching element type in the consuming app.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path as _FsPath
from typing import Iterable, Sequence

from .model import CubicMove, LineMove, QuadMove, Subpath

DOCTYPE_VERSION = 2

Point = Sequence[float]


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_meta(created: str | None = None) -> dict:
    return {"created": created or iso_now(), "doctype_version": DOCTYPE_VERSION}


def make_page(page_width: float, page_height: float, ws_width: float, ws_height: float) -> dict:
    return {
        "page_width": round(page_width, 4),
        "page_height": round(page_height, 4),
        "workspace_width": ws_width,
        "workspace_height": ws_height,
    }


def rgb_to_hex(color: tuple[float, float, float]) -> str:
    r, g, b = (max(0.0, min(1.0, c)) for c in color)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def make_pen(name: str, color: str, width: float) -> dict:
    return {"name": name, "color": color, "width": round(width, 4)}


def drawing_element(element_id: str, pen: int, z: int, points: Iterable[Point]) -> dict:
    return {
        "id": element_id,
        "type": "Drawing",
        "pen": pen,
        "z": z,
        "points": [[round(float(x), 4), round(float(y), 4)] for x, y in points],
    }


def _move_to_dict(move: LineMove | CubicMove | QuadMove) -> dict:
    if isinstance(move, LineMove):
        return {"type": "Line", "x1": move.x1, "y1": move.y1, "x2": move.x2, "y2": move.y2}
    if isinstance(move, CubicMove):
        return {
            "type": "CubicBezier",
            "x1": move.x1, "y1": move.y1,
            "cx1": move.cx1, "cy1": move.cy1,
            "cx2": move.cx2, "cy2": move.cy2,
            "x2": move.x2, "y2": move.y2,
        }
    return {
        "type": "QuadBezier",
        "x1": move.x1, "y1": move.y1,
        "cx": move.cx, "cy": move.cy,
        "x2": move.x2, "y2": move.y2,
    }


def stroke_to_dict(start: Point, moves: Sequence[LineMove | CubicMove | QuadMove]) -> dict:
    return {"start": [start[0], start[1]], "moves": [_move_to_dict(m) for m in moves]}


def subpath_to_stroke(subpath: Subpath, transform) -> dict:
    """Serialise a subpath to a ``PlotterStroke``, applying *transform* to points."""
    start = transform(*subpath.start)
    moves = []
    for move in subpath.moves:
        if isinstance(move, LineMove):
            a = transform(move.x1, move.y1)
            b = transform(move.x2, move.y2)
            moves.append({"type": "Line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1]})
        elif isinstance(move, CubicMove):
            a = transform(move.x1, move.y1)
            c1 = transform(move.cx1, move.cy1)
            c2 = transform(move.cx2, move.cy2)
            b = transform(move.x2, move.y2)
            moves.append({
                "type": "CubicBezier",
                "x1": a[0], "y1": a[1],
                "cx1": c1[0], "cy1": c1[1],
                "cx2": c2[0], "cy2": c2[1],
                "x2": b[0], "y2": b[1],
            })
        else:  # QuadMove
            a = transform(move.x1, move.y1)
            c = transform(move.cx, move.cy)
            b = transform(move.x2, move.y2)
            moves.append({
                "type": "QuadBezier",
                "x1": a[0], "y1": a[1],
                "cx": c[0], "cy": c[1],
                "x2": b[0], "y2": b[1],
            })
    return {"start": [start[0], start[1]], "moves": moves}


def path_element(element_id: str, pen: int, z: int, strokes: Sequence[dict]) -> dict:
    return {"id": element_id, "type": "Path", "pen": pen, "z": z, "strokes": list(strokes)}


def write_document(document: dict, destination: str | _FsPath, indent: int | None = 2) -> None:
    text = json.dumps(document, indent=indent)
    _FsPath(destination).write_text(text, encoding="utf-8")