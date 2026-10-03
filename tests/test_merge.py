"""Tests for joining polylines whose endpoints touch (pen-lift removal)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr.merge import DEFAULT_TOLERANCE_MM, merge_polylines  # noqa: E402


def segments(polylines):
    """Every drawn segment, normalised so direction does not matter."""
    out = []
    for points in polylines:
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            out.append(tuple(sorted(((round(ax, 6), round(ay, 6)),
                                     (round(bx, 6), round(by, 6))))))
    return sorted(out)


class MergeTests(unittest.TestCase):
    def test_touching_pieces_become_one_stroke(self):
        pieces = [("L", [(0, 0), (10, 0)]), ("L", [(10, 0), (20, 0)])]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][1], [(0, 0), (10, 0), (20, 0)])

    def test_piece_is_reversed_when_needed(self):
        pieces = [("L", [(0, 0), (10, 0)]), ("L", [(20, 0), (10, 0)])]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][1], [(0, 0), (10, 0), (20, 0)])

    def test_long_chain_collapses(self):
        pieces = [("L", [(0, 0), (5, 0)]), ("L", [(5, 0), (10, 0)]),
                  ("L", [(10, 0), (15, 0)])]
        self.assertEqual(len(merge_polylines(pieces)), 1)

    def test_out_of_order_pieces_still_join(self):
        pieces = [("L", [(0, 0), (5, 0)]), ("L", [(90, 90), (95, 90)]),
                  ("L", [(5, 0), (10, 0)])]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0][1], [(0, 0), (5, 0), (10, 0)])

    def test_rectangle_sides_join_into_one_stroke(self):
        pieces = [("L", [(0, 0), (5, 0)]), ("L", [(5, 0), (5, 5)]),
                  ("L", [(5, 5), (0, 5)]), ("L", [(0, 5), (0, 0)])]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][1][0], merged[0][1][-1])  # closed

    def test_junction_stops_the_stroke_without_retracing(self):
        # A T: the through-line joins, the stub becomes its own stroke.
        pieces = [("L", [(0, 0), (5, 0)]), ("L", [(5, 0), (10, 0)]),
                  ("L", [(5, 0), (5, 5)])]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0][1], [(0, 0), (5, 0), (10, 0)])
        self.assertEqual(merged[1][1], [(5, 0), (5, 5)])

    def test_four_way_junction_is_two_strokes(self):
        pieces = [("L", [(0, 0), (-1, 0)]), ("L", [(0, 0), (1, 0)]),
                  ("L", [(0, 0), (0, -1)]), ("L", [(0, 0), (0, 1)])]
        self.assertEqual(len(merge_polylines(pieces)), 2)

    def test_different_keys_are_never_joined(self):
        pieces = [("A", [(0, 0), (5, 0)]), ("B", [(5, 0), (10, 0)])]
        merged = merge_polylines(pieces)
        self.assertEqual([key for key, _ in merged], ["A", "B"])

    def test_gap_beyond_tolerance_is_not_joined(self):
        pieces = [("L", [(0, 0), (10, 0)]), ("L", [(10.5, 0), (20, 0)])]
        self.assertEqual(len(merge_polylines(pieces, 0.01)), 2)

    def test_gap_within_tolerance_is_joined(self):
        pieces = [("L", [(0, 0), (10, 0)]), ("L", [(10.005, 0), (20, 0)])]
        self.assertEqual(len(merge_polylines(pieces, 0.01)), 1)

    def test_zero_tolerance_joins_only_exact_touches(self):
        pieces = [("L", [(0, 0), (10, 0)]), ("L", [(10, 0), (20, 0)])]
        self.assertEqual(len(merge_polylines(pieces, 0.0)), 1)

    def test_negative_tolerance_disables_merging(self):
        pieces = [("L", [(0, 0), (10, 0)]), ("L", [(10, 0), (20, 0)])]
        self.assertEqual(merge_polylines(pieces, -1.0), [(k, list(p)) for k, p in pieces])

    def test_default_tolerance_is_ten_microns(self):
        self.assertEqual(DEFAULT_TOLERANCE_MM, 0.01)

    def test_order_follows_the_earliest_piece(self):
        pieces = [("L", [(0, 0), (1, 0)]), ("L", [(9, 9), (10, 9)]),
                  ("L", [(1, 0), (2, 0)])]
        merged = merge_polylines(pieces)
        self.assertEqual(merged[0][1], [(0, 0), (1, 0), (2, 0)])
        self.assertEqual(merged[1][1], [(9, 9), (10, 9)])

    def test_single_piece_is_returned_unchanged(self):
        pieces = [("L", [(0, 0), (1, 0)])]
        self.assertEqual(merge_polylines(pieces), [("L", [(0, 0), (1, 0)])])

    def test_no_segment_is_lost_or_drawn_twice(self):
        pieces = [
            ("L", [(0, 0), (10, 0)]),
            ("L", [(20, 0), (10, 0)]),
            ("L", [(10, 0), (10, 10)]),
            ("L", [(10, 10), (0, 10)]),
            ("L", [(0, 10), (0, 0)]),
            ("L", [(50, 50), (60, 50)]),
            ("L", [(5, 5), (0, 0)]),
        ]
        merged = merge_polylines(pieces)
        self.assertEqual(segments([p for _, p in pieces]), segments([p for _, p in merged]))
        self.assertLessEqual(len(merged), len(pieces))

    def test_zero_length_pieces_are_preserved(self):
        pieces = [("L", [(1, 1), (1, 1)]), ("L", [(1, 1), (2, 2)])]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][1], [(1, 1), (1, 1), (2, 2)])

    def test_self_touching_shape_is_one_stroke(self):
        pieces = [("L", [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
                  ("L", [(0, 0), (-1, 0), (-1, -1), (0, -1), (0, 0)])]
        self.assertEqual(len(merge_polylines(pieces)), 1)

    def test_large_chain_merges_completely(self):
        pieces = [("L", [(float(i), 0.0), (float(i + 1), 0.0)]) for i in range(200)]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0][1]), 201)

    def test_disconnected_components_are_all_kept(self):
        """Regression: a walk must never abandon the component it was asked for.

        The first four pieces form a closed loop, so every vertex of that
        component has even degree; the odd-degree vertices of the graph live in
        the star that follows. A walk that picked its start vertex globally
        would jump into the star and drop the loop edges on the floor.
        """
        pieces = [
            ("L", [(0, 0), (1, 0)]),
            ("L", [(1, 0), (1, 1)]),
            ("L", [(1, 1), (0, 1)]),
            ("L", [(0, 1), (0, 0)]),        # closed loop, all vertices even
            ("L", [(50, 0), (49, 0)]),      # star, the only odd vertices
            ("L", [(50, 0), (51, 0)]),
            ("L", [(50, 0), (50, 1)]),
        ]
        merged = merge_polylines(pieces)
        self.assertEqual(
            segments([p for _, p in pieces]), segments([p for _, p in merged])
        )
        drawn = {(a, b) for _, pts in merged for a, b in zip(pts, pts[1:])}
        self.assertIn(((0, 0), (1, 0)), {(tuple(a), tuple(b)) for a, b in drawn})

    def test_stars_in_separate_components_are_all_kept(self):
        """Several independent junctions must not cannibalise each other."""
        pieces = []
        for base in (0.0, 100.0, 200.0, 300.0):
            pieces += [
                ("L", [(base, 0.0), (base - 1, 0.0)]),
                ("L", [(base, 0.0), (base + 1, 0.0)]),
                ("L", [(base, 0.0), (base, -1)]),
                ("L", [(base, 0.0), (base, 1)]),
            ]
        merged = merge_polylines(pieces)
        self.assertEqual(len(merged), 8)  # four stars, two strokes each
        self.assertEqual(
            segments([p for _, p in pieces]), segments([p for _, p in merged])
        )

    def test_mixed_components_preserve_every_segment(self):
        """Chains, stars and lone lines together, interleaved and out of order."""
        pieces = [
            ("L", [(0, 0), (5, 0)]),
            ("L", [(90, 90), (90, 95)]),        # lonely line
            ("L", [(5, 0), (10, 0)]),
            ("L", [(10, 0), (9, 2)]),
            ("L", [(10, 0), (12, 2)]),
            ("L", [(10, 0), (13, -1)]),         # star of three at (10,0)
            ("L", [(50, 0), (55, 0)]),
            ("L", [(55, 0), (60, 0)]),
            ("L", [(60, 0), (65, 0)]),
        ]
        merged = merge_polylines(pieces)
        self.assertEqual(
            segments([p for _, p in pieces]), segments([p for _, p in merged])
        )
        # no stroke may be empty, and the point count may only drop by the joins
        self.assertTrue(all(len(pts) >= 2 for _, pts in merged))
        self.assertEqual(
            sum(len(pts) for _, pts in merged),
            sum(len(pts) for _, pts in pieces) - (len(pieces) - len(merged)),
        )


if __name__ == "__main__":
    unittest.main()
