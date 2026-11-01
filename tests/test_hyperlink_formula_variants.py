"""Regression: recognize valid HYPERLINK formulas before plain URL extraction."""
import ast
import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import MergedCell

SOURCE = Path(__file__).resolve().parents[1] / "app/services/excel.py"


def load_extractor():
    """Execute the actual extractor and regex from source without OCR imports."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"URL_RE", "HYPERLINK_FORMULA_RE", "LinkOccurrence", "_extract_occurrences"}
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            selected.append(node)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names:
            selected.append(node)
    namespace = {"re": re, "dataclass": dataclass, "MergedCell": MergedCell}
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(SOURCE), "exec"), namespace)
    return namespace["_extract_occurrences"]


class HyperlinkFormulaTests(unittest.TestCase):
    def setUp(self):
        self.extract = load_extractor()

    def assert_formula(self, formula):
        book = Workbook()
        book.active["B2"] = formula
        occurrences = self.extract(book)
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0].kind, "formula", f"Not classified as formula: {formula}")
        self.assertEqual(occurrences[0].url, "https://cdn.example.com/photo.png")
        self.assertEqual(occurrences[0].cell, "B2")

    def test_quoted_label_existing_format(self):
        self.assert_formula('=HYPERLINK("https://cdn.example.com/photo.png","Image")')

    def test_cell_reference_label(self):
        self.assert_formula('=HYPERLINK("https://cdn.example.com/photo.png",A1)')

    def test_absolute_cell_reference_label(self):
        self.assert_formula('=HYPERLINK("https://cdn.example.com/photo.png",$A$1)')

    def test_numeric_label(self):
        self.assert_formula('=HYPERLINK("https://cdn.example.com/photo.png",123)')

    def test_single_argument(self):
        self.assert_formula('=HYPERLINK("https://cdn.example.com/photo.png")')

    def test_nested_expression_label(self):
        self.assert_formula('=HYPERLINK("https://cdn.example.com/photo.png",IF(A1="Y","Yes","No"))')

    def test_semicolon_separator(self):
        self.assert_formula('=HYPERLINK("https://cdn.example.com/photo.png"; A1)')

    def test_plain_url_still_value(self):
        book = Workbook()
        book.active["A1"] = "Photo: https://cdn.example.com/photo.png"
        occurrences = self.extract(book)
        self.assertEqual([(o.url, o.kind) for o in occurrences], [("https://cdn.example.com/photo.png", "value")])

    def test_non_http_formula_not_extracted(self):
        book = Workbook()
        book.active["A1"] = '=HYPERLINK("file:///C:/private.png",A1)'
        self.assertEqual(self.extract(book), [])

    def test_malformed_empty_second_argument_not_classified_as_formula(self):
        book = Workbook()
        book.active["A1"] = '=HYPERLINK("https://cdn.example.com/photo.png",)'
        occurrences = self.extract(book)
        self.assertTrue(all(o.kind != "formula" for o in occurrences))


if __name__ == "__main__":
    unittest.main()
