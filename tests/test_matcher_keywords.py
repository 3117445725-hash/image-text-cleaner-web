"""Case-sensitive keyword parsing regression, including Unicode and CJK."""
import unittest

from app.services.matcher import match_text, parse_keywords


class KeywordParsingTests(unittest.TestCase):
    def test_case_sensitive_variants_remain_distinct(self):
        words = parse_keywords("Sale,sale,SALE", case_sensitive=True)
        self.assertEqual(words, ["Sale", "sale", "SALE"])
        self.assertEqual(match_text("sale", words, case_sensitive=True).matched_keywords, ("sale",))
        self.assertEqual(match_text("SALE", words, case_sensitive=True).matched_keywords, ("SALE",))

    def test_default_case_insensitive_behavior_unchanged(self):
        words = parse_keywords("Sale,sale,SALE")
        self.assertEqual(words, ["Sale"])
        self.assertEqual(match_text("sale", words).matched_keywords, ("Sale",))

    def test_unicode_nfkc_normalizes_before_dedupe(self):
        self.assertEqual(parse_keywords("ＡＢＣ,ABC,abc", case_sensitive=True), ["ABC", "abc"])
        self.assertEqual(parse_keywords("ＡＢＣ,ABC,abc"), ["ABC"])

    def test_cjk_and_word_boundaries(self):
        words = parse_keywords("配件,car")
        self.assertEqual(match_text("汽车配件", words).matched_keywords, ("配件",))
        self.assertFalse(match_text("cart", words).matched)
        self.assertEqual(match_text("car", words).matched_keywords, ("car",))

    def test_delimiters_whitespace_and_empty(self):
        self.assertEqual(parse_keywords(" A ；B，A;\n B "), ["A", "B"])
        self.assertEqual(parse_keywords("; , ；"), [])

    def test_unicode_casefold_default_merges(self):
        self.assertEqual(parse_keywords("Straße,STRASSE"), ["Straße"])

    def test_unicode_case_sensitive_preserves(self):
        self.assertEqual(parse_keywords("Straße,STRASSE", case_sensitive=True), ["Straße", "STRASSE"])

    def test_sensitive_dedupe_repeated_identical(self):
        self.assertEqual(parse_keywords("Sale,Sale,sale", case_sensitive=True), ["Sale", "sale"])


if __name__ == "__main__":
    unittest.main()
