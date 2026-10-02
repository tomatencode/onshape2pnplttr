"""Tests for affine geometry helpers."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr.geometry import (  # noqa: E402
    IDENTITY,
    Bounds,
    apply_mat,
    mat_mul,
    polyline_length,
    sample_cubic,
    sample_quad,
    scale_mat,
    translate_mat,
)


class MatrixTests(unittest.TestCase):
    def test_identity_is_noop(self):
        self.assertEqual(apply_mat(IDENTITY, 3.0, 4.0), (3.0, 4.0))

    def test_translate(self):
        self.assertEqual(apply_mat(translate_mat(10, -5), 1, 1), (11, -4))

    def test_scale(self):
        self.assertEqual(apply_mat(scale_mat(2), 3, 4), (6, 8))
        self.assertEqual(apply_mat(scale_mat(2, 0.5), 3, 4), (6, 2))

    def test_scale_then_translate_order(self):
        # scale first, then translate
        m = mat_mul(scale_mat(2), translate_mat(1, 1))
        self.assertEqual(apply_mat(m, 3, 3), (7, 7))
        # translate first, then scale
        m = mat_mul(translate_mat(1, 1), scale_mat(2))
        self.assertEqual(apply_mat(m, 3, 3), (8, 8))


class CurveTests(unittest.TestCase):
    def test_cubic_endpoints_and_count(self):
        pts = sample_cubic((0, 0), (1, 0), (2, 0), (3, 0), segments=4)
        self.assertEqual(len(pts), 4)
        self.assertAlmostEqual(pts[-1][0], 3.0)
        self.assertAlmostEqual(pts[-1][1], 0.0)

    def test_cubic_is_straight_line_for_collinear_controls(self):
        pts = sample_cubic((0, 0), (1, 0), (2, 0), (3, 0), segments=8)
        for x, y in pts:
            self.assertAlmostEqual(y, 0.0)
            self.assertGreaterEqual(x, 0.0)
            self.assertLessEqual(x, 3.0)

    def test_quad_endpoint(self):
        pts = sample_quad((0, 0), (1, 2), (2, 0), segments=4)
        self.assertEqual(pts[-1], (2.0, 0.0))
        self.assertGreater(max(p[1] for p in pts), 0.0)


class BoundsTests(unittest.TestCase):
    def test_accumulates_and_measures(self):
        bounds = Bounds()
        self.assertTrue(bounds.is_empty)
        bounds.add_points([(0, 0), (10, 5), (-2, 3)])
        self.assertFalse(bounds.is_empty)
        self.assertEqual((bounds.min_x, bounds.min_y), (-2, 0))
        self.assertEqual((bounds.max_x, bounds.max_y), (10, 5))
        self.assertEqual(bounds.width, 12)
        self.assertEqual(bounds.height, 5)

    def test_empty_dimensions_are_zero(self):
        self.assertEqual(Bounds().width, 0.0)
        self.assertEqual(Bounds().height, 0.0)


class LengthTests(unittest.TestCase):
    def test_polyline_length(self):
        self.assertAlmostEqual(polyline_length([(0, 0), (3, 0), (3, 4)]), 7.0)


if __name__ == "__main__":
    unittest.main()