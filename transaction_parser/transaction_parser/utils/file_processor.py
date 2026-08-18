import copy
import io
import zipfile

import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.utils.csvutils import read_csv_content
from frappe.utils.xlsxutils import (
    read_xls_file_from_attached_file,
    read_xlsx_file_from_attached_file,
)

from transaction_parser.transaction_parser.utils.pdf_processor import (
    PDFProcessor,
    get_pdf_processor,
)


def normalize_xlsx_content(file_content: bytes) -> bytes:
    """
    Rewrite XLSX zip entries written with OS path separators (xl\\workbook.xml),
    which openpyxl cannot look up. Returns content unchanged if already valid.
    """
    with zipfile.ZipFile(io.BytesIO(file_content)) as source:
        if not any("\\" in name for name in source.namelist()):
            return file_content

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                normalized_info = copy.copy(info)
                normalized_info.filename = info.filename.replace("\\", "/")
                target.writestr(normalized_info, source.read(info))

    return buffer.getvalue()


class FileProcessor:
    """
    Process files: PDF (trim pages, apply OCR), CSV/Excel (parse data), extract content.
    """

    def get_content(
        self,
        doc: File,
        page_limit: int | None = None,
        pdf_processor: PDFProcessor | None = None,
    ) -> str | None:
        if doc.file_type == "PDF":
            return self.process_pdf(doc, page_limit, pdf_processor)

        if doc.file_type in ("CSV", "XLSX", "XLS"):
            return self.process_spreadsheet(doc)

        frappe.throw(
            title=_("Unsupported File Type"),
            msg=_("Only PDF, CSV, and Excel files are supported"),
        )

    def process_pdf(
        self,
        doc: File,
        page_limit: int | None = None,
        pdf_processor: PDFProcessor | None = None,
    ) -> str:
        """
        Process PDF files using the configured PDF processor strategy.
        """
        pdf_processor = pdf_processor or get_pdf_processor()
        return pdf_processor.process(doc, page_limit)

    def process_spreadsheet(self, doc: File) -> str:
        """
        Process CSV and Excel files.
        """
        file_content = doc.get_content()

        if doc.file_type not in ("CSV", "XLSX", "XLS"):
            frappe.throw(
                title=_("Unsupported File Type"),
                msg=_(
                    "Cannot process spreadsheet with file type: {0}. <br> Supported types are CSV, XLSX, and XLS."
                ).format(doc.file_type),
            )

        if doc.file_type == "CSV":
            file_content_str = self.decode_csv_content(file_content)
            rows = read_csv_content(file_content_str)

        elif doc.file_type == "XLSX":
            rows = read_xlsx_file_from_attached_file(
                fcontent=normalize_xlsx_content(file_content)
            )

        elif doc.file_type == "XLS":
            rows = read_xls_file_from_attached_file(file_content)

        # Convert rows to a formatted string representation
        return self.format_rows_as_text(rows)

    def decode_csv_content(self, content: str | bytes) -> str:
        """
        Decode CSV file content with fallback encodings.
        """
        # If content is already a string, return as-is
        if isinstance(content, str):
            return content

        # If content is bytes, decode it
        # ! Note: Always keep `latin1` as the last fallback encoding, as it can decode any byte sequence without errors (Garbage)
        for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue

        frappe.throw(
            _(
                "Unable to decode CSV file. Please ensure the file is saved with a supported encoding."
            )
        )

    def format_rows_as_text(self, rows: list) -> str:
        """
        Convert rows to a text format suitable for AI processing.
        """
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
