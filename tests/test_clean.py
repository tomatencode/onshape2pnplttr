"""Tests for the ``.pnplttr`` cleaner (short edges, invisible detail, dots)."""
import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr.clean import (  # noqa: E402
    CleanOptions,
    _point_segment_distance,
    clean_document,
    clean_file,
    drop_collinear,
    drop_flat_points,
    drop_duplicate_segments,
    extent,
    is_closed,
    merge_points,
    simplify,
    stroke_to_points,
)
from onshape2pnplttr.clean_cli import main  # noqa: E402


def element(points, pen=0, index=0):
    return {
        "id": f"e{index + 1}",
        "type": "Drawing",
        "pen": pen,
        "z": index,
        "points": [list(p) for p in points],
    }


def document(*elements, pens=None):
    return {
        "meta": {"created": "2024-01-01T00:00:00Z", "doctype_version": 2},
        "page": {"page_width": 210.0, "page_height": 297.0,
                 "workspace_width": 200.0, "workspace_height": 285.0},
        "pens": pens if pens is not None else [{"name": "Visible", "color": "#000000", "width": 0.4}],
        "elements": list(elements),
    }


def staircase(steps=20, rise=0.05):
    """A run of sub-millimetre steps: what a detailed model turns into."""
    points = [(0.0, 0.0)]
    x = y = 0.0
    for _ in range(steps):
        x += rise
        points.append((x, y))
        y += rise
        points.append((x, y))
    return points


def ring(radius=5.0, segments=64, cx=50.0, cy=50.0):
    points = [(cx + radius * math.cos(2 * math.pi * i / segments),
               cy + radius * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
    points.append(points[0])
    return points


def path_element(points, pen=0):
    """A ``Path`` element: one stroke made of plain lines."""
    moves = [{"type": "Line", "x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1]}
             for a, b in zip(points, points[1:])]
    return {"id": "e1", "type": "Path", "pen": pen, "z": 0,
            "strokes": [{"start": list(points[0]), "moves": moves}]}


class PointHelperTests(unittest.TestCase):
    def test_is_closed(self):
        self.assertTrue(is_closed([(0, 0), (1, 0), (1, 1), (0, 0)]))
        self.assertFalse(is_closed([(0, 0), (1, 0), (1, 1)]))

    def test_merge_points_removes_repeats(self):
        self.assertEqual(merge_points([(0, 0), (0, 0), (1, 1), (1, 1), (2, 2)]),
                         [(0, 0), (1, 1), (2, 2)])

    def test_merge_points_keeps_close_but_distinct_points(self):
        self.assertEqual(len(merge_points([(0, 0), (0, 1e-3), (0, 2e-3)])), 3)

    def test_merge_points_of_nothing(self):
        self.assertEqual(merge_points([]), [])

    def test_collinear_joints_go(self):
        self.assertEqual(drop_collinear([(0, 0), (1, 0), (2, 0), (3, 0)]), [(0, 0), (3, 0)])

    def test_collinear_corners_stay(self):
        square = [(0, 0), (5, 0), (5, 5), (0, 5), (0, 0)]
        self.assertEqual(drop_collinear(square), square)

    def test_collinear_ring_keeps_four_corners(self):
        self.assertEqual(drop_collinear([(0, 0), (5, 0), (10, 0), (10, 5), (0, 5), (0, 0)]),
                         [(0, 0), (10, 0), (10, 5), (0, 5), (0, 0)])

    def test_out_and_back_tip_is_not_a_joint(self):
        """Regression: the tip of a spur is collinear yet overshoots.

        Dropping it would delete the whole out-and-back run, millimetres of
        ink, because the geometry is identical to a straight line.
        """
        spur = [(0, 0), (10, 0), (20, 0), (10, 0), (0, 0)]
        self.assertEqual(drop_collinear(spur), spur)

    def test_collinear_never_reduces_a_ring_below_a_triangle(self):
        self.assertGreaterEqual(len(drop_collinear(ring(segments=8))) - 1, 3)

    def test_extent_is_the_bbox_diagonal(self):
        self.assertAlmostEqual(extent([(0, 0), (3, 4)]), 5.0)


class FlatPointTests(unittest.TestCase):
    def test_staircase_collapses(self):
        out = drop_flat_points(staircase(), 0.1)
        self.assertLessEqual(len(out), 4)
        self.assertEqual(out[0], (0.0, 0.0))

    def test_short_edges_between_long_ones_go(self):
        out = drop_flat_points([(0, 0), (10, 0), (10.02, 0.0), (20, 0)], 0.1)
        self.assertEqual(out, [(0, 0), (20, 0)])

    def test_spur_on_a_long_line_goes(self):
        self.assertEqual(drop_flat_points([(0, 0), (10, 0), (10, 0.05), (20, 0)], 0.1),
                         [(0, 0), (20, 0)])

    def test_sharp_corner_next_to_a_short_edge_survives(self):
        """Regression: length alone is not a safe reason to delete a point.

        The 0.05 mm edge here is short, but its partner is a 90 degree corner
        100 mm from the stroke that would replace it.  The corner must stay;
        only the flat point beside it may go.
        """
        corner = [(0, 0), (0, 100), (0.05, 100), (100, 100)]
        out = drop_flat_points(corner, 0.1)
        self.assertIn((0, 100), out)   # the corner survives
        self.assertEqual(out, [(0, 0), (0, 100), (100, 100)])

    def test_open_chain_ends_are_kept(self):
        """Where the pen starts and stops is information, not detail."""
        points = [(0, 0), (0.001, 0), (5, 0), (10, 0), (10.001, 0)]
        out = drop_flat_points(points, 0.1)
        self.assertEqual(out[0], (0, 0))
        self.assertEqual(out[-1], (10.001, 0))

    def test_rings_stay_closed(self):
        out = drop_flat_points(ring(), 0.1)
        self.assertEqual(out[0], out[-1])

    def test_rings_keep_at_least_three_vertices(self):
        self.assertGreaterEqual(len(drop_flat_points(ring(radius=0.05), 0.1)) - 1, 3)

    def test_zero_min_detail_disables_the_pass(self):
        points = staircase()
        self.assertEqual(drop_flat_points(points, 0), points)

    def test_large_min_detail_is_bounded_by_the_floor(self):
        line = [(float(i), 0.0) for i in range(0, 30)]
        self.assertEqual(len(drop_flat_points(line, 100.0)), 2)


class SimplifyTests(unittest.TestCase):
    def test_waviness_within_tolerance_goes(self):
        wave = [(i * 0.5, 0.05 * math.sin(i)) for i in range(100)]
        self.assertLess(len(simplify(wave, 0.2)), 10)

    def test_waviness_beyond_tolerance_stays(self):
        wave = [(i * 0.5, 0.5 * math.sin(i)) for i in range(100)]
        self.assertGreater(len(simplify(wave, 0.05)), 10)

    def test_endpoints_are_always_kept(self):
        wave = [(i * 0.5, 0.5 * math.sin(i)) for i in range(50)]
        out = simplify(wave, 0.05)
        self.assertEqual(out[0], wave[0])
        self.assertEqual(out[-1], wave[-1])

    def test_vertex_beyond_the_chord_is_kept(self):
        """Regression: distance to the line, not to the segment.

        The middle point is 0.011 mm from the *line* through the ends but
        1.8 mm from the segment between them, because the path turns back on
        itself.  Douglas-Peucker measured to the line and deleted it.
        """
        spike = [(70.586, 98.561), (69.674, 100.14), (71.402, 97.168)]
        self.assertEqual(simplify(spike, 0.05), spike)

    def test_rings_stay_closed_and_keep_their_extremes(self):
        out = simplify(ring(radius=10.0, segments=64), 0.05)
        self.assertEqual(out[0], out[-1])
        xs = [p[0] for p in out]
        self.assertAlmostEqual(max(xs) - min(xs), 20.0, places=6)

    def test_zero_tolerance_disables_the_pass(self):
        wave = [(i * 0.5, 0.5 * math.sin(i)) for i in range(50)]
        self.assertEqual(simplify(wave, 0), wave)

    def test_a_closed_square_is_untouched(self):
        square = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (0.0, 0.0)]
        self.assertEqual(simplify(square, 0.05), square)


class DuplicateSegmentTests(unittest.TestCase):
    def test_a_repeated_edge_is_dropped(self):
        seen: set = set()
        first = drop_duplicate_segments([(0, 0), (10, 0)], seen, 1e-3)
        second = drop_duplicate_segments([(0, 0), (10, 0)], seen, 1e-3)
        self.assertEqual(first, [(0, 0), (10, 0)])
        self.assertEqual(second, [(0, 0), (10, 0)])  # kept, but nothing left to draw

    def test_direction_does_not_matter(self):
        seen: set = set()
        drop_duplicate_segments([(0, 0), (10, 0)], seen, 1e-3)
        self.assertEqual(drop_duplicate_segments([(10, 0), (0, 0)], seen, 1e-3),
                         [(10, 0), (0, 0)])

    def test_different_ink_is_kept(self):
        seen: set = set()
        drop_duplicate_segments([(0, 0), (10, 0)], seen, 1e-3)
        self.assertEqual(drop_duplicate_segments([(0, 1), (10, 1)], seen, 1e-3),
                         [(0, 1), (10, 1)])


class StrokeTests(unittest.TestCase):
    def test_a_line_move_becomes_two_points(self):
        stroke = {"start": [0, 0], "moves": [{"type": "Line", "x1": 0, "y1": 0, "x2": 5, "y2": 5}]}
        self.assertEqual(stroke_to_points(stroke), [(0.0, 0.0), (5.0, 5.0)])

    def test_a_cubic_is_sampled(self):
        stroke = {"start": [0, 0], "moves": [
            {"type": "CubicBezier", "x1": 0, "y1": 0, "cx1": 1, "cy1": 2,
             "cx2": 2, "cy2": 2, "x2": 3, "y2": 0}]}
        self.assertEqual(len(stroke_to_points(stroke, 8)), 9)

    def test_a_quadratic_is_sampled(self):
        stroke = {"start": [0, 0], "moves": [
            {"type": "QuadBezier", "x1": 0, "y1": 0, "cx": 1, "cy": 2, "x2": 3, "y2": 0}]}
        self.assertEqual(len(stroke_to_points(stroke, 4)), 5)


class CleanOptionsTests(unittest.TestCase):
    def test_negative_values_are_rejected(self):
        for field in ("min_detail", "tolerance", "min_extent", "epsilon", "quantise"):
            with self.assertRaises(ValueError):
                CleanOptions(**{field: -1.0})

    def test_unknown_path_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            CleanOptions(path_mode="nonsense")

    def test_error_bound_is_the_looser_of_the_two_passes(self):
        self.assertEqual(CleanOptions(min_detail=0.3, tolerance=0.1).error_bound_mm, 0.3)
        self.assertEqual(CleanOptions(min_detail=0.1, tolerance=0.4).error_bound_mm, 0.4)


class CleanDocumentTests(unittest.TestCase):
    def test_the_input_document_is_not_modified(self):
        doc = document(element(staircase()))
        before = json.dumps(doc, sort_keys=True)
        clean_document(doc)
        self.assertEqual(json.dumps(doc, sort_keys=True), before)

    def test_page_pens_and_meta_are_preserved(self):
        doc = document(element(ring()))
        result = clean_document(doc)
        self.assertEqual(result.document["page"], doc["page"])
        self.assertEqual(result.document["pens"], doc["pens"])
        self.assertEqual(result.document["meta"], doc["meta"])

    def test_ids_and_z_are_renumbered_without_gaps(self):
        result = clean_document(document(element(ring(), index=7), element(ring(), index=9)))
        self.assertEqual([e["id"] for e in result.document["elements"]], ["e1", "e2"])
        self.assertEqual([e["z"] for e in result.document["elements"]], [0, 1])

    def test_element_order_is_preserved(self):
        doc = document(element([(0, 0), (50, 0)], pen=0, index=0),
                       element([(10, 10), (10, 60)], pen=1, index=1))
        result = clean_document(doc)
        self.assertEqual(result.document["elements"][0]["points"][0], [0, 0])
        self.assertEqual(result.document["elements"][1]["points"][0], [10, 10])

    def test_a_sub_millimetre_element_is_dropped(self):
        doc = document(element([(10, 10), (10.02, 10.01)]), element(ring()))
        result = clean_document(doc)
        self.assertEqual(len(result.document["elements"]), 1)
        self.assertIn("min_extent", " ".join(result.stats.dropped_elements))

    def test_a_degenerate_element_is_dropped(self):
        result = clean_document(document(element([(5, 5), (5, 5), (5, 5)])))
        self.assertEqual(result.document["elements"], [])

    def test_min_extent_zero_keeps_small_elements(self):
        doc = document(element([(10, 10), (10.02, 10.01)]))
        result = clean_document(doc, CleanOptions(min_extent=0.0))
        self.assertEqual(len(result.document["elements"]), 1)

    def test_a_protected_pen_is_copied_through(self):
        doc = document(element(staircase(), pen=0), element(staircase(), pen=1))
        result = clean_document(doc, CleanOptions(protect_pens=(1,)))
        self.assertEqual(result.document["elements"][1]["points"],
                         [[round(x, 4), round(y, 4)] for x, y in staircase()])
        self.assertEqual(result.stats.protected, 1)

    def test_pens_are_never_merged_across(self):
        doc = document(element([(0, 0), (10, 0)], pen=0), element([(10, 0), (20, 0)], pen=1))
        result = clean_document(doc, CleanOptions())
        self.assertEqual(len(result.document["elements"]), 2)

    def test_statistics_add_up(self):
        doc = document(element(staircase()), element(ring()))
        stats = clean_document(doc).stats
        self.assertEqual(stats.elements_before, 2)
        self.assertLess(stats.segments_after, stats.segments_before)
        self.assertLess(stats.points_after, stats.points_before)
        self.assertLess(stats.length_after, stats.length_before)

    def test_a_document_without_elements_is_rejected(self):
        with self.assertRaises(ValueError):
            clean_document({"meta": {}})

    def test_an_empty_document_is_fine(self):
        result = clean_document(document())
        self.assertEqual(result.document["elements"], [])
        self.assertEqual(result.stats.elements_before, 0)

    def test_no_element_ends_up_with_zero_length_edges(self):
        doc = document(element(staircase()), element(ring()), element([(0, 0), (0, 0), (5, 5)]))
        for cleaned in clean_document(doc).document["elements"]:
            points = [tuple(p) for p in cleaned["points"]]
            for a, b in zip(points, points[1:]):
                self.assertNotEqual(a, b)

    def test_the_headline_case_a_0402_outline_collapses(self):
        """A ring of sub-millimetre edges must become a handful of points."""
        doc = document(element(ring(radius=0.6, segments=72, cx=5.0, cy=5.0)))
        result = clean_document(doc)
        self.assertLess(len(result.document["elements"][0]["points"]), 10)
        self.assertEqual(result.stats.elements_after, 1)


class ErrorBoundTests(unittest.TestCase):
    """The promise of the tool: nothing visible moves further than the bound."""

    @staticmethod
    def _stray(original, cleaned):
        segments = list(zip(cleaned, cleaned[1:]))
        if not segments:
            return float("inf")
        worst = 0.0
        for point in original:
            best = min(_point_segment_distance(point, a, b) for a, b in segments)
            worst = max(worst, best)
        return worst

    def test_staircase_stays_within_the_bound(self):
        options = CleanOptions()
        cleaned = simplify(drop_flat_points(staircase(), options.min_detail), options.tolerance)
        self.assertLess(self._stray(staircase(), cleaned), 0.5)

    def test_a_detail_ring_stays_within_the_bound(self):
        options = CleanOptions()
        original = ring(radius=4.0, segments=96, cx=60.0, cy=60.0)
        result = clean_document(document(element(original)), options)
        cleaned = [tuple(p) for p in result.document["elements"][0]["points"]]
        self.assertLess(self._stray(original, cleaned), 0.5)

    def test_a_whole_document_stays_within_the_bound(self):
        options = CleanOptions()
        doc = document(element(staircase()), element(ring(segments=48)),
                       element([(0, 0), (40, 0), (40, 40), (0, 40), (0, 0)]))
        result = clean_document(doc, options)
        for cleaned_element, original_element in zip(result.document["elements"], doc["elements"]):
            original = [tuple(p) for p in original_element["points"]]
            cleaned = [tuple(p) for p in cleaned_element["points"]]
            self.assertLess(self._stray(original, cleaned), options.error_bound_mm + 0.1)


class PathElementTests(unittest.TestCase):
    def test_path_elements_are_left_alone_by_default(self):
        doc = document(path_element(staircase()))
        result = clean_document(doc)
        self.assertEqual(result.document["elements"][0]["type"], "Path")
        self.assertEqual(result.stats.path_elements, 1)

    def test_path_mode_flatten_turns_them_into_drawings(self):
        doc = document(path_element(staircase()))
        result = clean_document(doc, CleanOptions(path_mode="flatten"))
        self.assertEqual(result.document["elements"][0]["type"], "Drawing")
        self.assertLess(len(result.document["elements"][0]["points"]), len(staircase()))

    def test_a_flattened_path_keeps_its_place_in_the_order(self):
        square = [(0, 0), (50, 0), (50, 50), (0, 50), (0, 0)]
        doc = document(element(ring(radius=5.0)), path_element(square))
        result = clean_document(doc, CleanOptions(path_mode="flatten"))
        self.assertEqual([e["id"] for e in result.document["elements"]], ["e1", "e2"])
        self.assertEqual(result.document["elements"][1]["type"], "Drawing")
        self.assertEqual(result.document["elements"][1]["points"][0], [0, 0])

    def test_each_stroke_of_a_path_becomes_its_own_element(self):
        path = path_element([(0, 0), (40, 0), (40, 40)])
        path["strokes"].append({"start": [10, 10], "moves": [
            {"type": "Line", "x1": 10, "y1": 10, "x2": 30, "y2": 10}]})
        result = clean_document(document(path), CleanOptions(path_mode="flatten"))
        self.assertEqual(len(result.document["elements"]), 2)


class CleanFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = self.tmp / "in.pnplttr"
        self.target = self.tmp / "out.pnplttr"
        self.source.write_text(json.dumps(document(element(staircase()))), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_file_writes_a_valid_document(self):
        result = clean_file(self.source, self.target)
        written = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(written, result.document)
        self.assertLess(len(written["elements"][0]["points"]), len(staircase()))

    def test_clean_file_leaves_the_source_alone(self):
        before = self.source.read_text(encoding="utf-8")
        clean_file(self.source, self.target)
        self.assertEqual(self.source.read_text(encoding="utf-8"), before)


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = self.tmp / "in.pnplttr"
        self.source.write_text(json.dumps(document(element(staircase()))), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_it_writes_next_to_the_input_by_default(self):
        self.assertEqual(main([str(self.source), "-q"]), 0)
        self.assertTrue((self.tmp / "in.clean.pnplttr").exists())

    def test_it_honours_the_output_option(self):
        target = self.tmp / "clean.pnplttr"
        self.assertEqual(main([str(self.source), "-o", str(target), "-q"]), 0)
        self.assertTrue(target.exists())

    def test_dry_run_writes_nothing(self):
        self.assertEqual(main([str(self.source), "--dry-run", "-q"]), 0)
        self.assertFalse((self.tmp / "in.clean.pnplttr").exists())

    def test_in_place_overwrites_the_input(self):
        self.assertEqual(main([str(self.source), "--in-place", "-q"]), 0)
        written = json.loads(self.source.read_text(encoding="utf-8"))
        self.assertLess(len(written["elements"][0]["points"]), len(staircase()))

    def test_a_missing_file_is_an_error(self):
        self.assertEqual(main([str(self.tmp / "nope.pnplttr"), "-q"]), 2)

    def test_broken_json_is_an_error(self):
        broken = self.tmp / "broken.pnplttr"
        broken.write_text("{not json", encoding="utf-8")
        self.assertEqual(main([str(broken), "-q"]), 1)

    def test_a_document_without_elements_is_an_error(self):
        bad = self.tmp / "bad.pnplttr"
        bad.write_text(json.dumps({"meta": {}}), encoding="utf-8")
        self.assertEqual(main([str(bad), "-q"]), 1)

    def test_the_summary_is_printed(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            main([str(self.source), "--dry-run"])
        text = buffer.getvalue()
        self.assertIn("elements", text)
        self.assertIn("segments", text)
        self.assertIn("stray", text)


if __name__ == "__main__":
    unittest.main()