"""Tests for the .pnplttr document builders."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr.model import CubicMove, LineMove, Subpath  # noqa: E402
from onshape2pnplttr import pnplttr  # noqa: E402


class SchemaTests(unittest.TestCase):
    def test_rgb_to_hex(self):
        self.assertEqual(pnplttr.rgb_to_hex((0.0, 0.0, 0.0)), "#000000")
        self.assertEqual(pnplttr.rgb_to_hex((1.0, 1.0, 1.0)), "#ffffff")
        self.assertEqual(pnplttr.rgb_to_hex((1.0, 0.0, 0.0)), "#ff0000")

    def test_rgb_to_hex_is_clamped(self):
        self.assertEqual(pnplttr.rgb_to_hex((-1.0, 2.0, 0.5)), "#00ff80")

    def test_meta_has_version(self):
        meta = pnplttr.make_meta()
        self.assertEqual(meta["doctype_version"], 2)
        self.assertIn("T", meta["created"])

    def test_make_page(self):
        page = pnplttr.make_page(210.0, 297.0, 200.0, 285.0)
        self.assertEqual(page["page_width"], 210.0)
        self.assertEqual(page["workspace_height"], 285.0)

    def test_make_pen(self):
        self.assertEqual(pnplttr.make_pen("Pen 1", "#2236b2", 0.6),
                         {"name": "Pen 1", "color": "#2236b2", "width": 0.6})

    def test_drawing_element_shape(self):
        element = pnplttr.drawing_element("e1", 0, 0, [(1.0, 2.0), (3.0, 4.0)])
        self.assertEqual(element, {"id": "e1", "type": "Drawing", "pen": 0, "z": 0,
                                   "points": [[1.0, 2.0], [3.0, 4.0]]})

    def test_subpath_to_stroke_line(self):
        subpath = Subpath(start=(0.0, 0.0), moves=[LineMove(0, 0, 5, 5)])
        stroke = pnplttr.subpath_to_stroke(subpath, lambda x, y: (x * 2, y * 2))
        self.assertEqual(stroke["start"], [0.0, 0.0])
        self.assertEqual(stroke["moves"][0], {"type": "Line", "x1": 0, "y1": 0, "x2": 10, "y2": 10})

    def test_subpath_to_stroke_cubic(self):
        subpath = Subpath(start=(0.0, 0.0), moves=[CubicMove(0, 0, 1, 1, 2, 1, 3, 0)])
        move = pnplttr.subpath_to_stroke(subpath, lambda x, y: (x, y))["moves"][0]
        self.assertEqual(move["type"], "CubicBezier")
        self.assertEqual((move["cx1"], move["cy1"]), (1.0, 1.0))

    def test_path_element_shape(self):
        element = pnplttr.path_element("e1", 0, 0, [{"start": [0, 0], "moves": []}])
        self.assertEqual(element["type"], "Path")
        self.assertEqual(len(element["strokes"]), 1)

    def test_write_document_roundtrip(self):
        doc = {"meta": pnplttr.make_meta(), "page": pnplttr.make_page(1, 1, 1, 1),
               "pens": [pnplttr.make_pen("p", "#000000", 0.4)], "elements": []}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "x.pnplttr"
            pnplttr.write_document(doc, out)
            self.assertEqual(json.loads(out.read_text()), doc)


if __name__ == "__main__":
    unittest.main()