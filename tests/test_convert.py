"""End-to-end conversion tests, including a synthetic in-memory PDF."""
import os
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr import ConvertOptions, convert_bytes, convert_pdf  # noqa: E402
from onshape2pnplttr.config import PT_TO_MM  # noqa: E402
from onshape2pnplttr.convert import _compute_layout  # noqa: E402

#: Optional real-world sample; set ONSHAPE2PNPLTTR_SAMPLE to override.
SAMPLE = Path(os.environ.get("ONSHAPE2PNPLTTR_SAMPLE", "/home/simon/Downloads/Drawing.pdf"))


def make_pdf(
    content: bytes,
    media_box=(0.0, 0.0, 792.0, 612.0),
    compress: bool = True,
    resources: bytes = b"<< >>",
    extra_objects: tuple[bytes, ...] = (),
) -> bytes:
    """Build a minimal single-page PDF around *content* (no xref needed)."""
    stream = zlib.compress(content) if compress else content
    filt = b"/Filter /FlateDecode " if compress else b""
    mb = " ".join(str(float(v)) for v in media_box).encode()
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [" + mb
        + b"] /Resources " + resources + b" /Contents 4 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Length " + str(len(stream)).encode() + b" " + filt
        + b">>\nstream\n" + stream + b"\nendstream\nendobj\n",
    ]
    objs.extend(extra_objects)
    return b"%PDF-1.5\n" + b"".join(objs) + b"trailer\n<< /Root 1 0 R /Size 5 >>\n%%EOF\n"


def all_points(document):
    for element in document["elements"]:
        if element["type"] == "Drawing":
            yield from element["points"]
class FitTests(unittest.TestCase):
    RECT = b"0 0 m 100 0 l 100 50 l 0 50 l h S"  # 100 x 50 pt rectangle

    def test_fit_scales_to_workspace(self):
        result = convert_bytes(make_pdf(self.RECT))
        page = result.document["page"]
        # 100 pt = 35.28 mm, fitted to 96% of a 200 mm workspace -> 192 mm wide.
        self.assertAlmostEqual(page["page_width"], 192.0, places=1)
        self.assertEqual(page["workspace_width"], 200.0)
        self.assertEqual(result.document["meta"]["doctype_version"], 2)

    def test_drawing_stays_within_page(self):
        document = convert_bytes(make_pdf(self.RECT)).document
        page = document["page"]
        for x, y in all_points(document):
            self.assertGreaterEqual(x, -1e-6)
            self.assertLessEqual(x, page["page_width"] + 1e-6)
            self.assertGreaterEqual(y, -1e-6)
            self.assertLessEqual(y, page["page_height"] + 1e-6)

    def test_actual_size_is_one_to_one(self):
        page = convert_bytes(make_pdf(self.RECT), ConvertOptions(fit="actual")).document["page"]
        self.assertAlmostEqual(page["page_width"], 100 * PT_TO_MM, places=2)
        self.assertAlmostEqual(page["page_height"], 50 * PT_TO_MM, places=2)

    def test_explicit_scale(self):
        result = convert_bytes(make_pdf(self.RECT), ConvertOptions(fit="scale", scale=2.0))
        self.assertAlmostEqual(result.document["page"]["page_width"], 200 * PT_TO_MM, places=2)

    def test_page_override_centres_artwork(self):
        opts = ConvertOptions(fit="actual", page=(300.0, 400.0))
        result = convert_bytes(make_pdf(self.RECT), opts)
        self.assertEqual(result.document["page"]["page_width"], 300.0)
        xs = [p[0] for p in all_points(result.document)]
        self.assertAlmostEqual(min(xs), (300.0 - 100 * PT_TO_MM) / 2, places=2)

    def test_gcode_centering_fits_workspace(self):
        document = convert_bytes(make_pdf(self.RECT)).document
        page = document["page"]
        x_off = (page["workspace_width"] - page["page_width"]) / 2
        y_off = (page["workspace_height"] - page["page_height"]) / 2
        for x, y in all_points(document):
            gx = x + x_off
            gy = page["workspace_height"] - (y + y_off)
            self.assertGreaterEqual(gx, -1e-6)
            self.assertLessEqual(gx, page["workspace_width"] + 1e-6)
            self.assertGreaterEqual(gy, -1e-6)
            self.assertLessEqual(gy, page["workspace_height"] + 1e-6)


class LayoutTests(unittest.TestCase):
    def test_fit_uses_margin(self):
        _, width, height = _compute_layout(100.0, 100.0, ConvertOptions(margin=0.02))
        self.assertAlmostEqual(width, 192.0)
        self.assertAlmostEqual(height, 192.0)

    def test_zero_size_is_not_scaled(self):
        scale, _, _ = _compute_layout(0.0, 0.0, ConvertOptions())
        self.assertEqual(scale, 1.0)


class ModeTests(unittest.TestCase):
    def test_path_mode_keeps_curves(self):
        content = b"0 0 m 0 10 10 10 10 0 c S"
        opts = ConvertOptions(element_mode="path")
        element = convert_bytes(make_pdf(content), opts).document["elements"][0]
        self.assertEqual(element["type"], "Path")
        self.assertEqual(element["strokes"][0]["moves"][0]["type"], "CubicBezier")

    def test_drawing_mode_flattens_curves(self):
        content = b"0 0 m 0 10 10 10 10 0 c S"
        opts = ConvertOptions(bezier_segments=8)
        element = convert_bytes(make_pdf(content), opts).document["elements"][0]
        self.assertEqual(element["type"], "Drawing")
        self.assertEqual(len(element["points"]), 9)  # start + 8 samples

    def test_includes_fills_by_default(self):
        content = b"0 0 m 10 0 l 10 10 l f 50 0 m 60 0 l S"
        self.assertEqual(len(convert_bytes(make_pdf(content)).document["elements"]), 2)

    def test_no_fills_drops_filled_regions(self):
        content = b"0 0 m 10 0 l 10 10 l f 50 0 m 60 0 l S"
        opts = ConvertOptions(include_fills=False)
LAYER_RESOURCES = b"<< /Properties << /OC0 5 0 R /OC1 6 0 R >> >>"
LAYER_OCGS = (
    b"5 0 obj\n<< /Type /OCG /Name (LayerA) >>\nendobj\n",
    b"6 0 obj\n<< /Type /OCG /Name (LayerB) >>\nendobj\n",
)
LAYER_CONTENT = (b"/OC /OC0 BDC 0 0 m 10 0 l S EMC "
                 b"/OC /OC1 BDC 0 20 m 10 20 l S EMC")


class LayerTests(unittest.TestCase):
    def _doc(self, options=None):
        pdf = make_pdf(LAYER_CONTENT, resources=LAYER_RESOURCES, extra_objects=LAYER_OCGS)
        return convert_bytes(pdf, options)

    def test_layer_names_are_read_from_the_pdf(self):
        result = self._doc()
        self.assertEqual(result.stats.used_layers, ["LayerA", "LayerB"])
        self.assertEqual([p["name"] for p in result.document["pens"]], ["LayerA", "LayerB"])

    def test_elements_reference_the_right_pen(self):
        self.assertEqual([e["pen"] for e in self._doc().document["elements"]], [0, 1])

    def test_drop_layer(self):
        result = self._doc(ConvertOptions(drop_layers=("LayerB",)))
        self.assertEqual(result.stats.used_layers, ["LayerA"])
        self.assertEqual(len(result.document["elements"]), 1)

    def test_per_layer_colour(self):
        result = self._doc(ConvertOptions(layer_colors={"LayerB": "#ff0000"}))
        pens = {p["name"]: p["color"] for p in result.document["pens"]}
        self.assertEqual(pens["LayerB"], "#ff0000")


class EmptyTests(unittest.TestCase):
    def test_empty_document_still_has_a_pen(self):
        result = convert_bytes(make_pdf(b"n"))
        self.assertEqual(result.document["elements"], [])
        self.assertEqual(len(result.document["pens"]), 1)
        self.assertTrue(result.stats.warnings)


class RealSampleTests(unittest.TestCase):
    @unittest.skipUnless(SAMPLE.exists(), f"sample not found at {SAMPLE}")
    def test_real_onshape_export(self):
        result = convert_pdf(SAMPLE)
        self.assertGreater(result.stats.elements, 1000)
        self.assertEqual(result.document["meta"]["doctype_version"], 2)
        self.assertGreater(len(result.document["pens"]), 1)
        page = result.document["page"]
        self.assertLessEqual(page["page_width"], page["workspace_width"] + 1e-6)
        self.assertLessEqual(page["page_height"], page["workspace_height"] + 1e-6)


if __name__ == "__main__":
    unittest.main()