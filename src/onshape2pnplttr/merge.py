"""Join polylines that touch, so a plotter keeps its pen down.

CAD exporters split a single continuous line across several subpaths: every
``m`` (moveto) operator in the PDF content stream starts a new subpath, even
when it lands exactly on the previous endpoint.  Emitting one element per
subpath therefore makes the plotter lift the pen at every split and travel
back to the same spot to carry on.

:func:`merge_polylines` walks the *touching* graph of the flattened polylines
and returns the same geometry as fewer, longer polylines.  Every input segment
is emitted exactly once; pieces may be reversed, which does not change the ink.
Nothing is dropped, duplicated or re-routed, so the plotted result is
unchanged -- only the pen lifts disappear.

At a junction (three or more polylines meeting) one stroke cannot pass
through all of them, so the walk stops and a new stroke starts there.  Segments
are deliberately *not* re-drawn to fake a continuous path: that would ink them
twice and leave darker lines on the plot.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Hashable, Sequence

from .geometry import Point

#: Default endpoint gap (mm) that still counts as "the same point".
DEFAULT_TOLERANCE_MM = 0.01

#: Above this many open edges in a group the bridge heuristic is skipped so
#: that pathologically dense artwork cannot turn merging into O(n^2) work.
_BRIDGE_LIMIT = 4000

Piece = tuple[Hashable, Sequence[Point]]


class _VertexCluster:
    """Collapse endpoints that lie within *tolerance* into shared vertices."""

    def __init__(self, tolerance: float) -> None:
        self._tol = tolerance
        self._grid: dict[tuple[int, int], list[Point]] = defaultdict(list)
        self._parent: dict[Point, Point] = {}
        self._keys: list[Point] = []

    @staticmethod
    def _key(pt: Point) -> Point:
        return (round(pt[0], 9), round(pt[1], 9))

    def _find(self, pt: Point) -> Point:
        root = pt
        while self._parent.get(root, root) != root:
            root = self._parent[root]
        while pt != root:
            self._parent[pt], pt = root, self._parent[pt]
        return root

    def _union(self, a: Point, b: Point) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            self._parent[rb] = ra

    def _cell(self, pt: Point) -> tuple[int, int]:
        span = max(self._tol, 1e-9)
        return int(math.floor(pt[0] / span)), int(math.floor(pt[1] / span))

    def _around(self, pt: Point):
        gx, gy = self._cell(pt)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                yield gx + dx, gy + dy

    def add(self, pt: Point) -> Point:
        """Register *pt* and return the key identifying its vertex."""
        key = self._key(pt)
        for cell in self._around(key):
            for other in self._grid.get(cell, ()):
                if math.dist(key, other) <= self._tol:
                    self._union(key, other)
        cell = self._cell(key)
        if key not in self._grid[cell]:
            self._grid[cell].append(key)
        self._keys.append(key)
        return key

    def find(self, pt: Point) -> Point:
        return self._find(self._key(pt))

    def ids(self) -> dict[Point, int]:
        """Canonical vertex ids, stable for every point added so far."""
        out: dict[Point, int] = {}
        for key in self._keys:
            root = self._find(key)
            if root not in out:
                out[root] = len(out)
        return out
def _is_bridge(
    edge: int,
    incident: dict[int, list[int]],
    unused: set[int],
    ends: list[tuple[int, int]],
) -> bool:
    """True when removing *edge* would cut the remaining graph in two."""
    a, b = ends[edge]
    if a == b:
        return False
    rest = unused - {edge}
    seen = {a}
    stack = [a]
    while stack:
        vertex = stack.pop()
        for other in incident[vertex]:
            if other not in rest:
                continue
            for end in ends[other]:
                if end not in seen:
                    seen.add(end)
                    stack.append(end)
    return b not in seen


def _choose(
    incident: dict[int, list[int]],
    unused: set[int],
    ends: list[tuple[int, int]],
    options: list[int],
) -> int:
    """Pick the next edge at a junction, preferring one that is not a bridge.

    At a plain junction (every other branch already leads somewhere else) any
    choice is fine; preferring a non-bridge keeps the rest of the component
    reachable so a chain is not stranded.
    """
    if len(options) == 1 or len(unused) > _BRIDGE_LIMIT:
        return options[0]
    for candidate in options:
        if not _is_bridge(candidate, incident, unused, ends):
            return candidate
    return options[0]


def _components(
    incident: dict[int, list[int]],
    ends: list[tuple[int, int]],
) -> dict[int, int]:
    """Label the connected component of every vertex of the touch graph."""
    label: dict[int, int] = {}
    for start in incident:
        if start in label:
            continue
        label[start] = start
        stack = [start]
        while stack:
            vertex = stack.pop()
            for edge in incident[vertex]:
                for other in ends[edge]:
                    if other not in label:
                        label[other] = start
                        stack.append(other)
    return label


def _merge_group(
    polylines: Sequence[Sequence[Point]],
    positions: Sequence[int],
    tolerance: float,
) -> list[tuple[int, list[Point]]]:
    """Merge one group of same-key polylines; returns ``(first input, points)``."""
    cluster = _VertexCluster(tolerance)
    keys = [cluster.add(poly[0]) for poly in polylines]
    keys += [cluster.add(poly[-1]) for poly in polylines]
    ids = cluster.ids()
    count = len(polylines)
    ends = [
        (ids[cluster.find(keys[i])], ids[cluster.find(keys[count + i])])
        for i in range(count)
    ]

    incident: dict[int, list[int]] = defaultdict(list)
    for index, (a, b) in enumerate(ends):
        incident[a].append(index)
        if b != a:
            incident[b].append(index)
        else:
            incident[a].append(index)  # a closed polyline meets itself twice
    rank = {vertex: edges[0] for vertex, edges in incident.items()}
    degree = {vertex: len(edges) for vertex, edges in incident.items()}
    odd = {vertex for vertex, count in degree.items() if count % 2}

    unused = set(range(count))
    results: list[tuple[int, list[Point]]] = []

    # Component of each vertex, so a walk can start on an odd vertex of the
    # component that still has work.  Starting anywhere else would leave the
    # current component untouched and its edges would never be visited.
    component = _components(incident, ends)

    while unused:
        start = min(unused)
        # A trail should begin (and end) at an odd-degree vertex, otherwise the
        # walk strands a branch: a four-way junction is two strokes, not four.
        here = component[ends[start][0]]
        candidates = [v for v in odd if component[v] == here]
        vertex = min(candidates, key=rank.__getitem__) if candidates else ends[start][0]
        used: list[int] = []
        points: list[Point] = []
        while True:
            options = [e for e in incident[vertex] if e in unused]
            if not options:
                break
            edge = _choose(incident, unused, ends, options)
            unused.discard(edge)
            used.append(edge)
            a, b = ends[edge]
            poly = polylines[edge]
            segment = list(poly) if a == vertex else list(reversed(poly))
            points.extend(segment if not points else segment[1:])
            vertex = b if a == vertex else a
            for touched in (a, b):
                degree[touched] -= 1
                if degree[touched] % 2:
                    odd.add(touched)
                else:
                    odd.discard(touched)
        results.append((min(positions[e] for e in used), points))

    assert not unused, "merge lost a polyline"
    return results


def merge_polylines(
    pieces: Sequence[Piece],
    tolerance: float = DEFAULT_TOLERANCE_MM,
) -> list[tuple[Hashable, list[Point]]]:
    """Join touching polylines that share a key, returning fewer, longer ones.

    *pieces* is a sequence of ``(key, points)`` pairs; the key groups pieces
    that may be joined (a CAD layer, i.e. one pen).  Two pieces join when the
    endpoint of one lies within *tolerance* of an endpoint of the other, so a
    line broken at a PDF moveto comes back as one stroke.

    Every input segment is returned exactly once and the relative order of the
    artwork is preserved: a merged stroke takes the position of its earliest
    constituent piece.  Reversal of a piece is allowed because it plots the same
    ink.  A tolerance of ``0`` joins only exactly coincident endpoints (the
    usual cause of the splits); a negative tolerance disables merging.
    """
    if tolerance < 0 or len(pieces) < 2:
        return [(key, list(points)) for key, points in pieces]

    groups: dict[Hashable, list[int]] = {}
    for index, (key, _) in enumerate(pieces):
        groups.setdefault(key, []).append(index)

    results: list[tuple[int, Hashable, list[Point]]] = []
    for key, indices in groups.items():
        polylines = [pieces[i][1] for i in indices]
        if any(len(poly) == 0 for poly in polylines):
            results.extend((i, key, list(pieces[i][1])) for i in indices)
            continue
        for position, points in _merge_group(polylines, indices, tolerance):
            results.append((position, key, points))

    results.sort(key=lambda item: item[0])
    return [(key, points) for _, key, points in results]

