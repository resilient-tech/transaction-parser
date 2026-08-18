"""Tests for spreadsheet file processing."""

import copy
import io
import zipfile
from unittest.mock import Mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file
from openpyxl import Workbook

from transaction_parser.transaction_parser.utils.file_processor import (
    FileProcessor,
    normalize_xlsx_content,
)

SAMPLE_ROWS = [
    ["Item Code", "Quantity", "Rate"],
    ["ITEM-001", 5, 100.5],
    ["ITEM-002", 2, 250.0],
]


def build_xlsx_content(rows: list) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def to_backslash_paths(file_content: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(file_content)) as source:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                renamed_info = copy.copy(info)
                renamed_info.filename = info.filename.replace("/", "\\")
                target.writestr(renamed_info, source.read(info))

    return buffer.getvalue()


class TestFileProcessor(FrappeTestCase):
    def test_normalize_xlsx_content_recovers_backslash_paths(self):
        content = to_backslash_paths(build_xlsx_content(SAMPLE_ROWS))

        with self.assertRaises(KeyError):
            read_xlsx_file_from_attached_file(fcontent=content)

        rows = read_xlsx_file_from_attached_file(
            fcontent=normalize_xlsx_content(content)
        )
        self.assertEqual(rows, SAMPLE_ROWS)

    def test_normalize_xlsx_content_leaves_valid_file_untouched(self):
        content = build_xlsx_content(SAMPLE_ROWS)
        self.assertIs(normalize_xlsx_content(content), content)

    def test_process_spreadsheet_parses_backslash_xlsx(self):
        doc = Mock(file_type="XLSX", file_name="orders.xlsx")
        doc.get_content.return_value = to_backslash_paths(
            build_xlsx_content(SAMPLE_ROWS)
        )

        content = FileProcessor().process_spreadsheet(doc)
        self.assertIn("ITEM-001", content)
        self.assertIn("Total rows: 3", content)
