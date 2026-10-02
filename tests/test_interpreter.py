"""Tests for the content-stream interpreter."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr.interpreter import Interpreter  # noqa: E402
from onshape2pnplttr.model import CubicMove, LineMove, PathKind  # noqa: E402


def run(content: str, **kwargs):
    return Interpreter(**kwargs).run(content.encode("latin1"))


class InterpreterTests(unittest.TestCase):
    def test_single_line(self):
        paths = run("10 10 m 20 30 l S")
        self.assertEqual(len(paths), 1)
        path = paths[0]
        self.assertEqual(path.kind, PathKind.STROKE)
        subpath = path.subpaths[0]
        self.assertEqual(subpath.start, (10.0, 10.0))
        self.assertIsInstance(subpath.moves[0], LineMove)
        self.assertEqual(subpath.moves[0].end, (20.0, 30.0))

    def test_unpainted_path_is_discarded(self):
        self.assertEqual(run("0 0 m 1 1 l n"), [])

    def test_graphics_state_is_restored(self):
        # 2x scale inside q/Q; the outer identity must apply afterwards.
        paths = run("q 2 0 0 2 0 0 cm 0 0 m 1 1 l S Q 0 0 m 3 3 l S")
        self.assertEqual(paths[0].subpaths[0].moves[0].end, (2.0, 2.0))
        self.assertEqual(paths[1].subpaths[0].moves[0].end, (3.0, 3.0))

    def test_line_width_and_colour(self):
        paths = run("0.5 w 1 0 0 RG 0 0 m 1 0 l S")
        self.assertEqual(paths[0].width, 0.5)
        self.assertEqual(paths[0].color, (1.0, 0.0, 0.0))

    def test_fill_kind(self):
        paths = run("0 0 m 10 0 l 10 10 l f")
        self.assertEqual(paths[0].kind, PathKind.FILL)

    def test_rectangle_helper(self):
        paths = run("0 0 10 20 re S")
        subpath = paths[0].subpaths[0]
        self.assertEqual(len(subpath.moves), 4)
        self.assertEqual(subpath.moves[-1].end, (0.0, 0.0))

    def test_close_path(self):
        subpath = run("0 0 m 10 0 l 10 10 l h S")[0].subpaths[0]
        self.assertEqual(subpath.moves[-1].end, (0.0, 0.0))

    def test_cubic_curve_is_preserved(self):
        subpath = run("0 0 m 0 10 10 10 10 0 c S")[0].subpaths[0]
        self.assertIsInstance(subpath.moves[0], CubicMove)

    def test_marked_content_selects_layer(self):
        paths = run("/OC /OC0 BDC 0 0 m 1 1 l S EMC", layer_names={"/OC0": "Visible"})
        self.assertEqual(paths[0].layer, "Visible")

    def test_unknown_marked_content_keeps_default_layer(self):
        paths = run("/OC /ZZ BDC 0 0 m 1 1 l S EMC",
                    layer_names={"/OC0": "Visible"}, default_layer="Default")
        self.assertEqual(paths[0].layer, "Default")


if __name__ == "__main__":
    unittest.main()