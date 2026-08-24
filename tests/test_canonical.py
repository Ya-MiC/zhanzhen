"""canonical JSON 契约测试 —— specs/events-v1.md Canonical 規則。"""

import unittest

from zhanzhen.canonical import canonical_json, canonical_sha256


class TestCanonical(unittest.TestCase):
    def test_key_order_is_byte_sorted_recursive(self):
        obj = {"b": 1, "a": {"d": 2, "c": 3}}
        self.assertEqual(canonical_json(obj), '{"a":{"c":3,"d":2},"b":1}')

    def test_no_whitespace(self):
        obj = {"x": [1, 2], "y": "中 文"}
        s = canonical_json(obj)
        self.assertNotIn(" ", s.replace("中 文", ""))

    def test_hash_stable_across_insertion_order(self):
        h1 = canonical_sha256({"a": 1, "b": 2})
        h2 = canonical_sha256({"b": 2, "a": 1})
        self.assertEqual(h1, h2)

    def test_float_int_distinct(self):
        self.assertNotEqual(canonical_json(5.0), canonical_json(5))
        self.assertEqual(canonical_json(5.0), "5.0")

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            canonical_sha256({"x": float("nan")})

    def test_unicode_not_escaped(self):
        self.assertEqual(canonical_json("湛箴"), '"湛箴"')


if __name__ == "__main__":
    unittest.main()
