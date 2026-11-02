"""Regression for exact URL removal without loading OCR/native runtime dependencies.

Compile the real URL regex and helper from excel.py, so this contract exercises
production source without initializing RapidOCR or making network requests.
"""
import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app/services/excel.py"


def _load_url_helper():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "URL_RE" for target in node.targets
        ):
            selected.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"_remove_url_from_text", "_trim_url_token"}:
            selected.append(node)
    if len(selected) != 3:
        raise AssertionError("URL_RE, _trim_url_token, and _remove_url_from_text must exist in production source")
    namespace = {"re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["_remove_url_from_text"], namespace["_trim_url_token"]


remove_url, trim_url = _load_url_helper()


class ExactUrlRemovalTests(unittest.TestCase):
    def test_short_url_does_not_corrupt_query_variant(self):
        short = "https://cdn.example.com/p.png"
        long = short + "?variant=2"
        self.assertEqual(remove_url(f"{short} | {long}", short), long)

    def test_short_url_does_not_corrupt_longer_filename(self):
        short = "https://cdn.example.com/p.png"
        long = short + "-large"
        self.assertEqual(remove_url(f"{short};{long}", short), long)

    def test_remove_exact_query_variant_preserves_base(self):
        base = "https://cdn.example.com/p.png"
        variant = base + "?variant=2"
        self.assertEqual(remove_url(f"{base}，{variant}", variant), base)

    def test_repeated_exact_urls_are_all_removed(self):
        url = "https://cdn.example.com/p.png"
        self.assertEqual(remove_url(f"{url} | {url}", url), None)

    def test_mixed_unrelated_urls_preserved(self):
        bad = "https://cdn.example.com/bad.png"
        good = "https://cdn.example.com/good.png"
        self.assertEqual(remove_url(f"{good};{bad};{good}", bad), f"{good};{good}")

    def test_only_matching_url_removed(self):
        good = "https://cdn.example.com/good.png"
        self.assertEqual(remove_url(good, "https://cdn.example.com/missing.png"), good)

    def test_single_url_becomes_empty_cell(self):
        self.assertIsNone(remove_url("https://cdn.example.com/bad.png", "https://cdn.example.com/bad.png"))

    def test_trailing_punctuation_not_part_of_url(self):
        bad = "https://cdn.example.com/bad.png"
        good = "https://cdn.example.com/good.png"
        self.assertEqual(remove_url(f"{bad}. | {good}", bad), f". | {good}")

    def test_case_distinct_url_is_not_accidentally_removed(self):
        upper = "https://cdn.example.com/A.png"
        lower = "https://cdn.example.com/a.png"
        self.assertEqual(remove_url(f"{upper}|{lower}", upper), lower)


    def test_valid_url_with_balanced_parentheses_is_not_truncated(self):
        url = "https://cdn.example.com/photo_(2)"
        self.assertEqual(trim_url(url), url)

    def test_extra_closing_parenthesis_and_sentence_punctuation_are_removed(self):
        url = "https://cdn.example.com/photo_(2)"
        self.assertEqual(trim_url(url + ")]."), url)

    def test_valid_balanced_square_brackets_are_preserved(self):
        url = "https://cdn.example.com/photo_[v2]"
        self.assertEqual(trim_url(url), url)

    def test_unmatched_square_bracket_is_trimmed(self):
        self.assertEqual(trim_url("https://cdn.example.com/photo.png]"), "https://cdn.example.com/photo.png")

    def test_remove_exact_balanced_url_preserves_other_balanced_url(self):
        bad = "https://cdn.example.com/photo_(2)"
        good = "https://cdn.example.com/photo_(3)"
        self.assertEqual(remove_url(f"{bad} | {good}", bad), good)

    def test_balanced_url_removal_preserves_surrounding_punctuation(self):
        bad = "https://cdn.example.com/photo_(2)"
        self.assertEqual(remove_url(f"({bad}).", bad), "().")



if __name__ == "__main__":
    unittest.main()
