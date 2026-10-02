"""2-D affine geometry helpers shared across the converter.

Coordinates flow through two spaces:

* **device space** -- PDF user units (points, y-up), after the content-stream
  transformation matrix has been applied.
* **document space** -- millimetres, y-down, as used by ``.pnplttr``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

Point = tuple[float, float]

# Affine matrix (a, b, c, d, e, f):
#     x' = a*x + c*y + e
#     y' = b*x + d*y + f
Mat = tuple[float, float, float, float, float, float]

IDENTITY: Mat = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m1: Mat, m2: Mat) -> Mat:
    """Return the matrix that applies *m1* first, then *m2*."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def translate_mat(tx: float, ty: float) -> Mat:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def scale_mat(sx: float, sy: float | None = None) -> Mat:
    if sy is None:
        sy = sx
    return (sx, 0.0, 0.0, sy, 0.0, 0.0)


def apply_mat(m: Mat, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def sample_cubic(p0: Point, p1: Point, p2: Point, p3: Point, segments: int = 16) -> list[Point]:
    """Sample a cubic Bézier, returning points *excluding* ``p0``."""
    out: list[Point] = []
    for i in range(1, segments + 1):
        t = i / segments
        mt = 1.0 - t
        x = (mt ** 3) * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + (t ** 3) * p3[0]
        y = (mt ** 3) * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + (t ** 3) * p3[1]
        out.append((x, y))
    return out


def sample_quad(p0: Point, p1: Point, p2: Point, segments: int = 16) -> list[Point]:
    """Sample a quadratic Bézier, returning points *excluding* ``p0``."""
    out: list[Point] = []
    for i in range(1, segments + 1):
        t = i / segments
        mt = 1.0 - t
        x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
        y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
        out.append((x, y))
    return out


@dataclass
class Bounds:
    """Axis-aligned bounding box accumulator."""

    min_x: float = math.inf
    min_y: float = math.inf
    max_x: float = -math.inf
    max_y: float = -math.inf

    def add(self, x: float, y: float) -> None:
        if x < self.min_x:
            self.min_x = x
        if y < self.min_y:
            self.min_y = y
        if x > self.max_x:
            self.max_x = x
        if y > self.max_y:
            self.max_y = y

    def add_points(self, points: Iterable[Point]) -> None:
        for x, y in points:
            self.add(x, y)

    @property
    def is_empty(self) -> bool:
        return self.min_x > self.max_x

    @property
    def width(self) -> float:
        return 0.0 if self.is_empty else self.max_x - self.min_x

    @property
    def height(self) -> float:
        return 0.0 if self.is_empty else self.max_y - self.min_y


def polyline_length(points: Sequence[Point]) -> float:
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        total += math.hypot(x1 - x0, y1 - y0)
    return total
