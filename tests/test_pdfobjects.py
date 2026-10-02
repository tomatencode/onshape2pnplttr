"""Tests for the recursive PDF object parser and object scanner."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr.pdfobjects import Parser, Ref, iter_objects, parse  # noqa: E402


class ParserTests(unittest.TestCase):
    def test_scalars_and_names(self):
        self.assertEqual(parse(b"/Type /Page"), "/Type")

    def test_number(self):
        self.assertEqual(parse(b"42"), 42.0)

    def test_array(self):
        self.assertEqual(parse(b"[0 0 792 612]"), [0.0, 0.0, 792.0, 612.0])

    def test_dictionary_and_references(self):
        value = parse(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1 1] >>")
        self.assertEqual(value["/Type"], "/Page")
        self.assertEqual(value["/Parent"], Ref(2, 0))
        self.assertEqual(value["/MediaBox"], [0.0, 0.0, 1.0, 1.0])

    def test_string_value_is_bytes(self):
        self.assertEqual(parse(b"(hello)"), b"hello")

    def test_iter_objects_finds_all(self):
        data = b"<<\n1 0 obj\n<< /A 1 >>\nendobj\n2 0 obj\n(hi)\nendobj\n>>"
        objects = {num: body for num, _gen, body in iter_objects(data)}
        self.assertEqual(set(objects), {1, 2})
        self.assertIn(b"/A 1", objects[1])

    def test_parser_at_end(self):
        p = Parser(b"1 2")
        self.assertFalse(p.at_end())
        p.parse_value()
        p.parse_value()
        self.assertTrue(p.at_end())


if __name__ == "__main__":
    unittest.main()