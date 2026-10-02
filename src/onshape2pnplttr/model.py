"""Geometry model produced by the content-stream interpreter.

This mirrors PenPlotterApp's canonical ``PlotterStroke`` / ``PlotterMove``
types so the interpreter output can be emitted either as flattened ``Drawing``
polylines or as lossless ``Path`` strokes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .geometry import Point, sample_cubic, sample_quad


@dataclass(frozen=True)
class LineMove:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def start(self) -> Point:
        return (self.x1, self.y1)

    @property
    def end(self) -> Point:
        return (self.x2, self.y2)

    def sample(self, _curves: bool, _segments: int = 16) -> list[Point]:
        return [(self.x2, self.y2)]


@dataclass(frozen=True)
class CubicMove:
    x1: float
    y1: float
    cx1: float
    cy1: float
    cx2: float
    cy2: float
    x2: float
    y2: float

    @property
    def start(self) -> Point:
        return (self.x1, self.y1)

    @property
    def end(self) -> Point:
        return (self.x2, self.y2)

    def sample(self, curves: bool, segments: int = 16) -> list[Point]:
        if not curves:
            return [(self.x2, self.y2)]
        return sample_cubic(self.start, (self.cx1, self.cy1), (self.cx2, self.cy2), self.end, segments)


@dataclass(frozen=True)
class QuadMove:
    x1: float
    y1: float
    cx: float
    cy: float
    x2: float
    y2: float

    @property
    def start(self) -> Point:
        return (self.x1, self.y1)

    @property
    def end(self) -> Point:
        return (self.x2, self.y2)

    def sample(self, curves: bool, segments: int = 16) -> list[Point]:
        if not curves:
            return [(self.x2, self.y2)]
        return sample_quad(self.start, (self.cx, self.cy), self.end, segments)


Move = LineMove | CubicMove | QuadMove


@dataclass
class Subpath:
    """A single pen-down run: ``start`` followed by connected moves."""

    start: Point
    moves: list[Move] = field(default_factory=list)

    @property
    def end(self) -> Point:
        return self.moves[-1].end if self.moves else self.start

    def polyline(self, curves: bool = True, segments: int = 16) -> list[Point]:
        pts = [self.start]
        for move in self.moves:
            pts.extend(move.sample(curves, segments))
        return pts

    def iter_points(self, curves: bool = True, segments: int = 16):
        yield self.start
        for move in self.moves:
            yield from move.sample(curves, segments)


class PathKind(str, Enum):
    STROKE = "stroke"
    FILL = "fill"


@dataclass
class Path:
    """A painted path: one or more subpaths sharing a graphics state."""

    layer: str
    kind: PathKind
    width: float
    color: tuple[float, float, float]
    subpaths: list[Subpath] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(len(sp.moves) > 0 for sp in self.subpaths)