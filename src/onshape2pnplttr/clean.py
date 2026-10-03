"""Remove geometry a pen cannot draw from a generated ``.pnplttr`` document.

A detailed CAD model is made of far more edges than a plotter can usefully
ink: in a real OnShape export 73% of the segments are shorter than 0.05 mm,
an order of magnitude below the 0.4 mm pen.  They cost plot time, they are
invisible on their own, and where many of them meet they blot the paper -- the
ink spills that make a finished plot look messy.

:func:`clean_document` is a chain of local passes over the polylines of a
finished document.  Every pass has a geometric bound, so the tool's promise is
simple: **ink is only removed where the pen could not have drawn it anyway.**

====================  =========================================================
pass                  guarantee
====================  =========================================================
``merge_points``      zero-length edges removed (no ink change at all)
``drop_collinear``    points on the chord of their neighbours go (no ink change)
``drop_flat_points``  each point dropped strays less than ``min_detail``
``simplify``          Douglas-Peucker: the result stays within ``tolerance``
micro elements        whole elements smaller than ``min_extent`` go
``dedupe_segments``   only ink that was already drawn elsewhere
====================  =========================================================

``drop_flat_points`` and ``simplify`` attack different defects, which is why
both are needed.  ``simplify`` compares a point with the chord spanning a whole
edge, so a locally flat but globally significant detail survives it;
``drop_flat_points`` compares a point with the chord through its two
*neighbours*, which is what catches short edges, staircases and the tip of a
spur -- the "dozens of sub-mm lines" this tool exists to delete.  Flat points
go first and Douglas-Peucker runs last, so the tolerance is measured against
what is actually left.

Both measure the distance to the chord **segment** rather than to the
infinite line through it.  CAD geometry is full of paths that run out along a
line and back along it again, and their tips are collinear yet far outside the
segment between their neighbours; measuring to the line would silently swallow
millimetres of real ink.

Closed rings -- most CAD contours are closed -- are handled cyclically
throughout, and a ring is never reduced below a triangle.

The defaults are derived from the pen: with a 0.4 mm nib, ``min_detail``
0.1 mm, ``tolerance`` 0.05 mm and ``min_extent`` 0.2 mm all stay under the
width of a single stroke, so nothing that could still be seen is removed.
Raise them for a faster plot, lower them for a cautious one.
"""
from __future__ import annotations

import copy
import heapq
import json
import math
from dataclasses import dataclass, field
from pathlib import Path as _FsPath
from typing import Sequence

from .geometry import polyline_length, sample_cubic, sample_quad

#: Points closer than this (mm) count as the same spot.
DEFAULT_EPSILON_MM = 1e-6

#: Drop points whose removal moves the stroke by less than this (mm) -- a
#: quarter of the default pen width.
DEFAULT_MIN_DETAIL_MM = 0.1

#: Douglas-Peucker tolerance (mm) -- an eighth of the default pen width.
DEFAULT_SIMPLIFY_MM = 0.05

#: Drop whole elements whose bounding box is smaller than this (mm).
DEFAULT_MIN_EXTENT_MM = 0.2

#: Coordinate quantum (mm) below which two segments count as the same ink.
DEFAULT_QUANTISE_MM = 1e-3

PATH_MODES = ("skip", "flatten")

Point = tuple[float, float]


# --------------------------------------------------------------------------
# options and results
# --------------------------------------------------------------------------
@dataclass
class CleanOptions:
    """Everything tunable about a cleanup.

    ``min_detail`` drops the detail a pen cannot resolve (short edges,
    staircases, spur tips), ``tolerance`` is the Douglas-Peucker budget for
    waviness along a long edge, and ``min_extent`` drops whole elements too
    small to render at all.  A value of ``0`` switches that pass off.
    """

    min_detail: float = DEFAULT_MIN_DETAIL_MM
    tolerance: float = DEFAULT_SIMPLIFY_MM
    min_extent: float = DEFAULT_MIN_EXTENT_MM
    epsilon: float = DEFAULT_EPSILON_MM

    drop_degenerate: bool = True  # elements with fewer than two distinct points
    dedupe_segments: bool = False  # drop ink drawn twice (lightens the paper)
    quantise: float = DEFAULT_QUANTISE_MM

    path_mode: str = "skip"  # "skip" leaves Path elements alone, "flatten" draws them
    bezier_segments: int = 16

    protect_pens: tuple[int, ...] = ()  # pens that are copied through untouched

    def __post_init__(self) -> None:
        for name in ("min_detail", "tolerance", "min_extent", "epsilon"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.quantise < 0:
            raise ValueError("quantise must be >= 0")
        if self.path_mode not in PATH_MODES:
            raise ValueError(f"path_mode must be one of {PATH_MODES}, got {self.path_mode!r}")
        if self.bezier_segments < 1:
            raise ValueError("bezier_segments must be >= 1")

    @property
    def error_bound_mm(self) -> float:
        """The distance the pen can be asked to stray, in millimetres.

        Both passes compare against a *segment*, so a point is only ever
        dropped if the stroke that replaces it passes that close to it.  Chains
        of such removals add up along a path, so this is the per-removal bound,
        not a bound on the whole drawing.
        """
        return max(self.tolerance, self.min_detail)


@dataclass
class CleanStats:
    """What the cleaner removed, for the CLI summary."""

    elements_before: int = 0
    elements_after: int = 0
    points_before: int = 0
    points_after: int = 0
    segments_before: int = 0
    segments_after: int = 0
    length_before: float = 0.0
    length_after: float = 0.0

    dropped_elements: dict[str, int] = field(default_factory=dict)
    removed_points: dict[str, int] = field(default_factory=dict)
    duplicate_segments: int = 0
    path_elements: int = 0
    protected: int = 0
    pens: list[tuple[str, int, int]] = field(default_factory=list)  # name, before, after

    def dropped(self, reason: str, count: int = 1) -> None:
        if count:
            self.dropped_elements[reason] = self.dropped_elements.get(reason, 0) + count

    def removed(self, reason: str, count: int) -> None:
        if count:
            self.removed_points[reason] = self.removed_points.get(reason, 0) + count

    @property
    def points_removed(self) -> int:
        return max(self.points_before - self.points_after, 0)


@dataclass
class CleanResult:
    document: dict
    stats: CleanStats


# --------------------------------------------------------------------------
# polyline helpers
# --------------------------------------------------------------------------
def is_closed(points: Sequence[Point], epsilon: float = 0.0) -> bool:
    """True when a polyline runs back to its start, i.e. it is a CAD contour."""
    return len(points) > 2 and math.dist(points[0], points[-1]) <= max(epsilon, 0.0)


def merge_points(points: Sequence[Point], epsilon: float = DEFAULT_EPSILON_MM) -> list[Point]:
    """Drop points that repeat their predecessor, i.e. zero-length edges."""
    if not points:
        return []
    out: list[Point] = [points[0]]
    for point in points[1:]:
        if math.dist(point, out[-1]) > epsilon:
            out.append(point)
    return out


def _cross(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    """Twice the area of the triangle ``a b c``."""
    return abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    """Distance from *p* to the **segment** *a b*.

    The segment, not the infinite line: CAD geometry is full of paths that run
    out along a line and back along it again, and the tip of such a spur lies
    on the line while being nowhere near the segment between its neighbours.
    Measuring to the line would silently swallow millimetres of real ink.
    """
    vx, vy = b[0] - a[0], b[1] - a[1]
    length = vx * vx + vy * vy
    if length == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / length
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)


def _is_joint(a: Point, b: Point, c: Point, epsilon: float) -> bool:
    """True when *b* only joins the straight run *a -> b -> c*.

    Both halves of the test matter.  The cross product says the three points
    are in line, and the dot product says *b* is **between** *a* and *c*: a CAD
    artefact often runs out along a line and back along the same line, and the
    tip of such a spur is collinear yet overshoots.  Dropping that tip would
    delete millimetres of visible ink, so it is kept.
    """
    if (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) < 0:
        return False  # b overshoots c: the path turns back here
    return _cross(*a, *b, *c) <= epsilon * math.dist(a, c)


def drop_collinear(points: Sequence[Point], epsilon: float = DEFAULT_EPSILON_MM) -> list[Point]:
    """Remove points lying on the straight line between their neighbours.

    CAD exporters happily split one straight edge into a dozen pieces; the
    joints carry no information, and dropping them is free -- the ink is
    identical.  It also stops the flatness pass and Douglas-Peucker from
    looking at points that cannot change a decision.
    """
    points = list(points)
    if len(points) < 3:
        return points
    if is_closed(points, epsilon):
        ring = points[:-1]
        out: list[Point] = []
        for index, point in enumerate(ring):
            if not out:
                out.append(point)  # always anchor the ring at its first vertex
                continue
            after = ring[(index + 1) % len(ring)]
            # The last three vertices stay whatever they are: below that a
            # ring is no longer a shape.
            if len(ring) - len(out) > 3 and _is_joint(out[-1], point, after, epsilon):
                continue
            out.append(point)
        if len(out) < 3:  # a degenerate ring keeps its joints
            return points
        return out + [out[0]]
    out = [points[0]]
    for index in range(1, len(points) - 1):
        if not _is_joint(out[-1], points[index], points[index + 1], epsilon):
            out.append(points[index])
    out.append(points[-1])
    merged = merge_points(out, epsilon)
    return merged if len(merged) >= 2 else points


def _prune_flat(core: list[Point], min_detail: float, closed: bool, floor: int) -> list[Point]:
    """Delete the flattest vertices of a chain or a ring until none is left.

    A vertex is *flat* when the stroke drawn through its two neighbours passes
    within ``min_detail`` of it.  Deleting a flat vertex moves the ink by at
    most ``min_detail`` -- that is the whole guarantee -- while a sharp corner
    is never flat and therefore always survives.

    This is what removes short lines.  A 0.05 mm edge has flat endpoints; a
    staircase is flat all the way down; the tip of a spur is flat against the
    line between its neighbours.  Testing *flatness* rather than *length* is
    what keeps a genuine corner that merely happens to be followed by a short
    edge, where a length test would happily cut the corner off.

    The flattest vertex is always taken first, and every removal re-queues its
    two neighbours, so a whole run of detail collapses in one sweep.
    """
    count = len(core)
    if count <= floor:
        return list(core)

    prev = [(i - 1) % count for i in range(count)] if closed else list(range(-1, count - 1))
    nxt = [(i + 1) % count for i in range(count)] if closed else list(range(1, count + 1))
    if not closed:
        nxt[count - 1] = -1

    alive = [True] * count

    def deviation(index: int) -> float:
        before, after = prev[index], nxt[index]
        if before == -1 or after == -1:
            # An end of an open chain has no chord through both neighbours,
            # and where the pen starts and stops is worth keeping.
            return math.inf
        return _point_segment_distance(core[index], core[before], core[after])

    # Lazy deletion: an entry records the neighbours it measured, so it can be
    # recognised as stale once one of them has gone or moved on.
    heap: list[tuple[float, int, int, int]] = []
    for index in range(count):
        value = deviation(index)
        if value < math.inf:
            heap.append((value, index, prev[index], nxt[index]))
    heapq.heapify(heap)

    remaining = count
    while remaining > floor and heap:
        value, index, before, after = heapq.heappop(heap)
        if not alive[index] or prev[index] != before or nxt[index] != after:
            continue  # stale entry: this vertex now has other neighbours
        if value > min_detail:
            break  # the flattest vertex left is not flat enough, so none is
        alive[index] = False
        remaining -= 1
        if before != -1:
            nxt[before] = after
        if after != -1:
            prev[after] = before
        for neighbour in (before, after):
            if neighbour != -1 and alive[neighbour] and remaining > floor:
                fresh = deviation(neighbour)
                if fresh < math.inf:
                    heapq.heappush(heap, (fresh, neighbour, prev[neighbour], nxt[neighbour]))

    out = [core[i] for i in range(count) if alive[i]]
    return out if len(out) >= floor else list(core)


def drop_flat_points(
    points: Sequence[Point],
    min_detail: float = DEFAULT_MIN_DETAIL_MM,
    epsilon: float = DEFAULT_EPSILON_MM,
) -> list[Point]:
    """Drop points whose removal moves the stroke by less than *min_detail*.

    This is the pass that answers "a detailed model turns every edge into a
    line": a 0402 capacitor outline arrives as a ring of sub-millimetre
    segments, and each of them costs the plotter a move.  Chains of them --
    staircases, serrations, the little steps along a fill boundary -- collapse
    in one sweep, because every removal re-queues its neighbours.
    """
    points = list(points)
    if min_detail <= 0 or len(points) < 4:
        return points
    if is_closed(points, epsilon):
        ring = _prune_flat(points[:-1], min_detail, closed=True, floor=3)
        if len(ring) < 3:
            return points
        return ring + [ring[0]]
    return _prune_flat(points, min_detail, closed=False, floor=2)


def _simplify_open(points: Sequence[Point], tolerance: float) -> list[Point]:
    """Douglas-Peucker on an open chain; the two endpoints always survive.

    Deviation is measured to the chord **segment**, not to the infinite line
    through it, so a vertex that sits beyond the chord -- the tip of a path
    that runs out and comes back -- counts as far away and is kept.
    """
    count = len(points)
    keep = bytearray(count)
    keep[0] = keep[count - 1] = 1
    stack = [(0, count - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        start, end = points[first], points[last]
        best = -1.0
        split = -1
        for index in range(first + 1, last):
            distance = _point_segment_distance(points[index], start, end)
            if distance > best:
                best, split = distance, index
        if best > tolerance:
            keep[split] = 1
            stack.append((first, split))
            stack.append((split, last))
    return [points[i] for i in range(count) if keep[i]]


def simplify(
    points: Sequence[Point],
    tolerance: float = DEFAULT_SIMPLIFY_MM,
    epsilon: float = DEFAULT_EPSILON_MM,
) -> list[Point]:
    """Douglas-Peucker simplification, closed rings included.

    Unlike :func:`drop_short_edges` this also removes the redundant points of
    a *long* edge: a gently wavy contour costs the plotter hundreds of moves
    while reading as a straight line at plotter resolution.  Every dropped
    point was within ``tolerance`` of the line that replaces it, so the error
    is bounded by construction.

    A closed ring has no endpoints to anchor the recursion, so it is cut at
    the point furthest from its start into two open chains, simplified
    separately and glued back together: the ring stays closed and its extreme
    points stay put.
    """
    points = list(points)
    if tolerance <= 0 or len(points) < 3:
        return points
    if not is_closed(points, epsilon):
        return _simplify_open(points, tolerance)

    ring = points[:-1]
    if len(ring) < 4:
        return points
    anchor = max(range(1, len(ring)), key=lambda i: math.dist(ring[0], ring[i]))
    head = _simplify_open(ring[: anchor + 1], tolerance)
    tail = _simplify_open(ring[anchor:] + [ring[0]], tolerance)
    if len(head) < 2 or len(tail) < 2:
        return points
    # ``tail`` already starts at the anchor and ends back at the start of the
    # ring, so dropping ``head``'s last point closes it without a duplicate.
    stitched = head[:-1] + tail
    return stitched if len(stitched) >= 3 else points


def drop_duplicate_segments(
    points: Sequence[Point],
    seen: set,
    quantise: float = DEFAULT_QUANTISE_MM,
    epsilon: float = DEFAULT_EPSILON_MM,
) -> list[Point]:
    """Drop edges some earlier element of the same pen already drew.

    Off by default: it halves the ink weight where two lines overlap, which
    for overplotted CAD geometry is usually a win but is a *visible* change
    rather than an invisible one.  An edge is removed by dropping its start
    vertex, so the rest of the polyline stays connected.
    """
    points = list(points)
    if not points or quantise <= 0:
        return points
    step = max(quantise, 1e-9)
    closed = is_closed(points, epsilon)
    core = points[:-1] if closed else points
    out: list[Point] = []
    kept: Point | None = None
    for point in core:
        if kept is not None:
            a = (round(kept[0] / step), round(kept[1] / step))
            b = (round(point[0] / step), round(point[1] / step))
            if a != b:
                key = (a, b) if a <= b else (b, a)
                if key in seen:
                    kept = point  # already drawn elsewhere: drop this vertex
                    continue
                seen.add(key)
        out.append(point)
        kept = point
    if closed:
        return out + [out[0]] if len(out) >= 3 else points
    merged = merge_points(out, epsilon)
    return merged if len(merged) >= 2 else points


def extent(points: Sequence[Point]) -> float:
    """Diagonal of the bounding box: how much paper a polyline can cover."""
    if not points:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def stroke_to_points(stroke: dict, segments: int = 16) -> list[Point]:
    """Flatten one ``PlotterStroke`` of a ``Path`` element into a polyline.

    In ``drawing`` mode the pen follows a flattened polyline anyway, so
    ``--path-mode flatten`` cleans curves by exactly the ink they produce.
    """
    start = stroke.get("start") or [0.0, 0.0]
    points: list[Point] = [(float(start[0]), float(start[1]))]
    for move in stroke.get("moves") or []:
        tail = points[-1]
        end = (float(move.get("x2", tail[0])), float(move.get("y2", tail[1])))
        kind = move.get("type")
        if kind == "CubicBezier":
            points.extend(sample_cubic(tail, (move["cx1"], move["cy1"]),
                                       (move["cx2"], move["cy2"]), end, segments))
        elif kind == "QuadBezier":
            points.extend(sample_quad(tail, (move["cx"], move["cy"]), end, segments))
        else:
            points.append(end)
    return points


# --------------------------------------------------------------------------
# document cleaning
# --------------------------------------------------------------------------
def _pen_index(element: dict) -> int:
    """The pen an element draws with, tolerating a missing or bogus field."""
    try:
        return int(element.get("pen", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _drawing_points(element: dict) -> list[Point] | None:
    """The polyline of a ``Drawing`` element, or ``None`` for anything else."""
    if element.get("type", "Drawing") != "Drawing":
        return None
    return [(float(x), float(y)) for x, y in (element.get("points") or [])]


def _measure(points: Sequence[Point]) -> tuple[int, int, float]:
    """``(segments, points, pen-down length)`` of one polyline."""
    return max(len(points) - 1, 0), len(points), polyline_length(points)


def _clean_polyline(points: Sequence[Point], options: CleanOptions, stats: CleanStats) -> list[Point]:
    """Run the geometry passes over one polyline, recording what they removed.

    The order matters: joints that carry no information go first, then the
    sub-pen-width detail, and Douglas-Peucker runs last so its tolerance is
    measured against what is actually left to draw.
    """
    epsilon = options.epsilon
    out = list(points)
    for name, step in (
        ("duplicate points", lambda pts: merge_points(pts, epsilon)),
        ("collinear points", lambda pts: drop_collinear(pts, epsilon)),
        ("flat points", lambda pts: drop_flat_points(pts, options.min_detail, epsilon)),
        ("simplified", lambda pts: simplify(pts, options.tolerance, epsilon)),
        ("duplicate points", lambda pts: merge_points(pts, epsilon)),
    ):
        reduced = step(out)
        stats.removed(name, len(out) - len(reduced))
        out = reduced
    return out


def clean_document(document: dict, options: CleanOptions | None = None) -> CleanResult:
    """Return a cleaned copy of a ``.pnplttr`` document, plus statistics.

    The input document is left untouched.  Element order is preserved so the
    artwork keeps its plotting sequence, and ids and ``z`` indices are
    renumbered so the result is a valid document again.
    """
    options = options or CleanOptions()
    if not isinstance(document, dict) or "elements" not in document:
        raise ValueError("not a .pnplttr document: no 'elements' array")

    stats = CleanStats()
    pens = document.get("pens") or []

    # -- Path elements: leave them, or flatten them into drawings --------
    working: list[dict] = []
    if options.path_mode == "flatten":
        for element in document["elements"]:
            if element.get("type") == "Path":
                stats.path_elements += 1
                for stroke in element.get("strokes") or []:
                    working.append({
                        "type": "Drawing",
                        "pen": element.get("pen", 0),
                        "points": stroke_to_points(stroke, options.bezier_segments),
                    })
            else:
                working.append(element)
    else:
        working = list(document["elements"])
        stats.path_elements = sum(1 for e in working if e.get("type") == "Path")

    stats.elements_before = len(working)
    before_pens: dict[int, int] = {}
    for element in working:
        pen = _pen_index(element)
        before_pens[pen] = before_pens.get(pen, 0) + 1
        points = _drawing_points(element) or []
        segments, count, length = _measure(points)
        stats.points_before += count
        stats.segments_before += segments
        stats.length_before += length

    protected = set(options.protect_pens)
    seen_edges: set = set()
    after_pens: dict[int, int] = {}
    # ``points is None`` marks an element that is copied through untouched
    # (a ``Path`` element in ``skip`` mode); otherwise it is the new polyline.
    cleaned: list[tuple[int, list[Point] | None, dict]] = []

    for element in working:
        pen = _pen_index(element)
        points = _drawing_points(element)
        if points is None:
            cleaned.append((pen, None, element))
            continue
        if pen in protected:
            stats.protected += 1
            cleaned.append((pen, points, element))
            continue

        # -- elements too small for the pen to render ------------------
        if options.drop_degenerate and len(merge_points(points, options.epsilon)) < 2:
            stats.dropped("degenerate (no length)")
            continue
        if options.min_extent > 0 and extent(points) < options.min_extent:
            stats.dropped("smaller than min_extent")
            continue

        out = _clean_polyline(points, options, stats)
        if options.dedupe_segments:
            before = len(out)
            out = drop_duplicate_segments(out, seen_edges, options.quantise, options.epsilon)
            stats.duplicate_segments += max(0, before - len(out))
        if options.drop_degenerate and len(merge_points(out, options.epsilon)) < 2:
            stats.dropped("emptied by cleaning")
            continue
        cleaned.append((pen, out, element))

    # -- rebuild the element list ---------------------------------------
    # Cleaning never joins polylines: the converter already merges the ones
    # that touch (``--merge``), and a stroke is only ever shortened here, so
    # no two endpoints that were apart can suddenly meet.
    elements: list[dict] = []
    for index, (pen, points, original) in enumerate(cleaned):
        if points is None:
            elements.append({**original, "id": f"e{index + 1}", "z": index})
            after_pens[pen] = after_pens.get(pen, 0) + 1
            continue
        if len(points) < 2:
            continue  # nothing drawable is left
        after_pens[pen] = after_pens.get(pen, 0) + 1
        segments, count, length = _measure(points)
        stats.points_after += count
        stats.segments_after += segments
        stats.length_after += length
        elements.append({
            "id": f"e{index + 1}",
            "type": "Drawing",
            "pen": pen,
            "z": index,
            "points": [[round(x, 4), round(y, 4)] for x, y in points],
        })
    stats.elements_after = len(elements)
    stats.pens = [
        (pens[pen].get("name", f"Pen {pen + 1}") if pen < len(pens) else f"Pen {pen + 1}",
         before_pens.get(pen, 0), after_pens.get(pen, 0))
        for pen in sorted(set(before_pens) | set(after_pens))
    ]

    cleaned_document = copy.deepcopy(document)
    cleaned_document["elements"] = elements
    return CleanResult(cleaned_document, stats)


def clean_file(
    source: str | _FsPath,
    destination: str | _FsPath,
    options: CleanOptions | None = None,
    indent: int | None = 2,
) -> CleanResult:
    """Read a ``.pnplttr``, clean it and write the result to *destination*."""
    text = _FsPath(source).read_text(encoding="utf-8")
    result = clean_document(json.loads(text), options)
    _FsPath(destination).write_text(json.dumps(result.document, indent=indent), encoding="utf-8")
    return result