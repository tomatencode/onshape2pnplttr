"""Tests for the content-stream tokenizer."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from onshape2pnplttr.content import decode_name, tokenize  # noqa: E402


def kinds(data: bytes):
    return [(t.kind, t.value) for t in tokenize(data)]


class TokenizerTests(unittest.TestCase):
    def test_numbers_names_operators(self):
        self.assertEqual(
            kinds(b"10 -2.5 .5 /Foo m"),
            [("num", 10.0), ("num", -2.5), ("num", 0.5), ("name", "/Foo"), ("op", "m")],
        )

    def test_arrays_and_dicts(self):
        self.assertEqual(
            kinds(b"[1 2] << /A 3 >>"),
            [("[", None), ("num", 1.0), ("num", 2.0), ("]", None),
             ("<<", None), ("name", "/A"), ("num", 3.0), (">>", None)],
        )

    def test_literal_string_with_nested_parens(self):
        self.assertEqual(kinds(b"(a(b)c)"), [("str", b"a(b)c")])

    def test_string_escapes(self):
        self.assertEqual(kinds(b"(a\\nb)"), [("str", b"a\nb")])
        self.assertEqual(kinds(b"(\\101)"), [("str", b"A")])

    def test_comments_are_skipped(self):
        self.assertEqual(kinds(b"1 % comment\n2"), [("num", 1.0), ("num", 2.0)])

    def test_hex_string(self):
        self.assertEqual(kinds(b"<48656C6C6F>"), [("hex", b"48656C6C6F")])

    def test_multichar_operators(self):
        self.assertEqual(
            kinds(b"0 0 0 RG 1 0 0 rg"),
            [("num", 0.0), ("num", 0.0), ("num", 0.0), ("op", "RG"),
             ("num", 1.0), ("num", 0.0), ("num", 0.0), ("op", "rg")],
        )

    def test_name_hash_escape(self):
        self.assertEqual(decode_name("/A#20B"), "/A B")


if __name__ == "__main__":
    unittest.main()