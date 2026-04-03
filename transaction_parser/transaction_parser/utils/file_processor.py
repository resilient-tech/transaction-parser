import io

import frappe
import ocrmypdf
import pymupdf
from frappe import _
from frappe.utils.csvutils import read_csv_content
from frappe.utils.xlsxutils import (
    read_xls_file_from_attached_file,
    read_xlsx_file_from_attached_file,
)

from transaction_parser.exceptions import FileProcessingError


class FileProcessor:
    """Process files: PDF (trim pages, apply OCR), CSV/Excel (parse data), extract content."""

    def get_content(self, doc, page_limit=None):
        try:
            if doc.file_type == "PDF":
                return self._process_pdf(doc, page_limit)
            elif doc.file_type in ["CSV", "XLSX", "XLS"]:
                return self._process_spreadsheet(doc)
            else:
                frappe.throw(_("Only PDF, CSV, and Excel files are supported"))

        except Exception as e:
            raise FileProcessingError from e

    def _process_pdf(self, doc, page_limit=None):
        """Process PDF files with OCR and page limiting."""
        self.file = io.BytesIO(doc.get_content())
        self._remove_extra_pages(page_limit)
        self._apply_ocr()
        return self._get_text()

    def _process_spreadsheet(self, doc):
        """Process CSV and Excel files."""
        file_content = doc.get_content()

        if doc.file_type == "CSV":
            file_content_str = self._decode_csv_content(file_content)
            rows = read_csv_content(file_content_str)
        elif doc.file_type == "XLSX":
            rows = read_xlsx_file_from_attached_file(fcontent=file_content)
        elif doc.file_type == "XLS":
            rows = read_xls_file_from_attached_file(file_content)

        # Convert rows to a formatted string representation
        return self._format_rows_as_text(rows)

    def _decode_csv_content(self, content):
        """Decode CSV file content with fallback encodings."""
        # If content is already a string, return as-is
        if isinstance(content, str):
            return content

        # If content is bytes, decode it
        encodings = ["utf-8", "utf-8-sig", "latin1", "cp1252"]

        for encoding in encodings:
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue

        # If all encodings fail, try with error handling
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            frappe.throw(
                _(
                    "Unable to decode CSV file. Please ensure the file is saved with a supported encoding."
                )
            )

    def _format_rows_as_text(self, rows):
        """Convert rows to a text format suitable for AI processing."""
        if not rows:
            frappe.throw(_("No data found in the file."))

        # Create a structured text representation
        text_parts = []

        # Check if this looks like key-value pairs (2 columns)
        if len(rows) > 0 and len(rows[0]) == 2:
            # Format as key-value pairs
            text_parts.append("Document Information (Key-Value pairs):")
            text_parts.append("")
            for row in rows:
                key = str(row[0] or "").strip()
                value = str(row[1] or "").strip()
                if key and value:
                    text_parts.append(f"{key}: {value}")
        else:
            # Format as regular table
            # First row is typically headers
            headers = " | ".join(str(cell or "") for cell in rows[0])
            text_parts.append(f"Columns: {headers}")
            text_parts.append("")

            # Add data rows (skip header row)
            text_parts.append("Data:")
            for index, row in enumerate(rows[1:], 1):
                row_data = " | ".join(str(cell or "") for cell in row)
                text_parts.append(f"Row {index}: {row_data}")

        # Add summary information
        text_parts.append("")
        text_parts.append(f"Total rows: {len(rows)}")
        text_parts.append(f"Total columns: {len(rows[0])}")

        return "\n".join(text_parts)

    def _remove_extra_pages(self, page_limit=None):
        if not page_limit:
            return

        input_pdf = pymupdf.open(stream=self.file, filetype="pdf")
        output_pdf = pymupdf.open()
        output_pdf.insert_pdf(input_pdf, to_page=page_limit - 1)

        temp_file = io.BytesIO()
        output_pdf.save(temp_file)

        output_pdf.close()
        input_pdf.close()

        self.file = temp_file
        self.file.seek(0)

    def _apply_ocr(self):
        doc = pymupdf.open(stream=self.file, filetype="pdf")
        pages_to_ocr = [
            str(i) for i, page in enumerate(doc, 1) if not page.get_text("text").strip()
        ]

        if not pages_to_ocr:
            return

        pages = ",".join(pages_to_ocr)

        temp_file = io.BytesIO()
        self.file.seek(0)

        ocrmypdf.ocr(
            input_file=self.file,
            output_file=temp_file,
            pages=pages,
            progress_bar=False,
            rotate_pages=True,
            force_ocr=True,
        )

        self.file = temp_file
        self.file.seek(0)

    def _get_text(self):
        text = ""
        doc = pymupdf.open(stream=self.file, filetype="pdf")
        for page in doc:
            text += page.get_text("text")

        doc.close()

        return text
