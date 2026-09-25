import io
from abc import ABC, abstractmethod

import frappe
from frappe import _
from frappe.core.doctype.file.file import File


class PDFProcessor(ABC):
    """
    Abstract base class for PDF processors.

    To add a new processor from another app:

    1. Subclass PDFProcessor
    2. Implement the `process` method
    3. Register it via the `pdf_processors` hook in your app's hooks.py:

    ```
    pdf_processors = {
        "MyProcessor": "my_app.utils.pdf_processor.MyPDFProcessor",
    }
    ```
    """

    @abstractmethod
    def process(self, file: io.BytesIO | File, page_limit: int | None = None) -> str:
        """
        Process a PDF file and return extracted text.

        Args:
            file: PDF file as BytesIO stream or Frappe File document
            page_limit: Maximum number of pages to process (None = all pages)

        Returns:
                Extracted text content from the PDF
        """
        pass

    def get_sanitized_file(
        self, file: io.BytesIO | File, page_limit: int | None = None
    ) -> io.BytesIO:
        """
        Get file as BytesIO stream and trim pages if needed.
        """
        if isinstance(file, File):
            file = io.BytesIO(file.get_content())

        return self.trim_pages(file, page_limit)

    def trim_pages(self, file: io.BytesIO, page_limit: int | None = None) -> io.BytesIO:
        import pymupdf

        if not page_limit or page_limit <= 0:
            file.seek(0)
            return file

        input_pdf = pymupdf.open(stream=file, filetype="pdf")

        if input_pdf.page_count <= page_limit:
            input_pdf.close()
            file.seek(0)
            return file

        output_pdf = pymupdf.open()
        output_pdf.insert_pdf(input_pdf, to_page=page_limit - 1)

        temp_file = io.BytesIO()
        output_pdf.save(temp_file)

        output_pdf.close()
        input_pdf.close()

        temp_file.seek(0)
        return temp_file

    def get_text(self, file: io.BytesIO) -> str:
        import pymupdf

        text = ""
        doc = pymupdf.open(stream=file, filetype="pdf")

        for page in doc:
            text += page.get_text("text")

        doc.close()

        return text


class DoclingPDFProcessor(PDFProcessor):
    """
    PDF processor using Docling for document conversion and text extraction.

    Docling provides advanced document understanding including table detection,
    formula recognition, reading order detection, and OCR.
    """

    _converter = None

    SETUP_URL = (
        "https://github.com/resilient-tech/transaction-parser#3-docling-optional"
    )

    def process(self, file: io.BytesIO | File, page_limit: int | None = None) -> str:
        try:
            from docling.datamodel.base_models import ConversionStatus, DocumentStream
        except ImportError:
            frappe.throw(
                title=_("Missing Dependency"),
                msg=_(
                    "docling is not installed.<br>"
                    "Install it with: <code>bench pip install transaction_parser[docling]</code><br>"
                    "See <a href='{0}'>setup instructions</a> for more details."
                ).format(self.SETUP_URL),
            )

        file = self.get_sanitized_file(file, page_limit)

        source = DocumentStream(name="document.pdf", stream=file)  # temporary name
        converter = self._get_converter()
        result = converter.convert(source)

        if (
            not result
            or not result.document
            or result.status
            not in (
                ConversionStatus.SUCCESS,
                ConversionStatus.PARTIAL_SUCCESS,
            )
        ):
            frappe.throw(
                title=_("PDF Reading Failed"),
                msg=_("Docling failed to read the document."),
            )

        return result.document.export_to_markdown()

    def _get_converter(self):
        if DoclingPDFProcessor._converter is None:
            try:
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import (
                    EasyOcrOptions,
                    PdfPipelineOptions,
                )
                from docling.document_converter import (
                    DocumentConverter,
                    PdfFormatOption,
                )
            except ImportError:
                frappe.throw(
                    title=_("Missing Dependency"),
                    msg=_(
                        "docling is not installed.<br>"
                        "Install it with: <code>bench pip install transaction_parser[docling]</code><br>"
                        "See <a href='{0}'>setup instructions</a> for more details."
                    ).format(self.SETUP_URL),
                )

            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = True
            pipeline_options.ocr_options = EasyOcrOptions()

            DoclingPDFProcessor._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                }
            )

        return DoclingPDFProcessor._converter


class PDFtoTextProcessor(PDFProcessor):
    """
    PDF processor using pdftotext for layout-preserving text extraction.
    """

    SETUP_URL = (
        "https://github.com/resilient-tech/transaction-parser#1-pdftotext-default"
    )

    def process(self, file: io.BytesIO | File, page_limit: int | None = None) -> str:
        file = self.get_sanitized_file(file, page_limit)
        return self.get_text(file)

    def get_text(self, file: io.BytesIO) -> str:
        try:
            import pdftotext
        except ImportError:
            frappe.throw(
                title=_("Missing Dependency"),
                msg=_(
                    "pdftotext is not installed.<br>"
                    "Install OS dependencies first if not already installed: "
                    "<code>sudo apt install build-essential libpoppler-cpp-dev pkg-config python3-dev</code>"
                    "<br>Then run: <code>bench setup requirements</code><br>"
                    "See <a href='{0}'>setup instructions</a> for more details."
                ).format(self.SETUP_URL),
            )

        pdf = pdftotext.PDF(file, physical=True)

        return "\n\n".join(page.strip() for page in pdf if page.strip())


class OCRMyPDFProcessor(PDFProcessor):
    """
    PDF processor using PyMuPDF for text extraction and OCRMyPDF for OCR.
    """

    SETUP_URL = (
        "https://github.com/resilient-tech/transaction-parser#2-ocrmypdf-optional"
    )

    def process(self, file: io.BytesIO | File, page_limit: int | None = None) -> str:
        file = self.get_sanitized_file(file, page_limit)
        file = self.apply_ocr(file)

        return self.get_text(file)

    def apply_ocr(self, file: io.BytesIO) -> io.BytesIO:
        try:
            import ocrmypdf
        except ImportError:
            frappe.throw(
                title=_("Missing Dependency"),
                msg=_(
                    "ocrmypdf is not installed.<br>"
                    "Install it with: <code>bench pip install transaction_parser[ocrmypdf]</code><br>"
                    "See <a href='{0}'>setup instructions</a> for more details."
                ).format(self.SETUP_URL),
            )

        file.seek(0)

        temp_file = io.BytesIO()

        ocrmypdf.ocr(
            input_file=file,
            output_file=temp_file,
            progress_bar=False,
            rotate_pages=True,
            force_ocr=True,
        )

        temp_file.seek(0)
        return temp_file


DEFAULT_PDF_PROCESSOR = "PDFtoText"

BUILTIN_PDF_PROCESSORS = {
    "PDFtoText": "transaction_parser.transaction_parser.utils.pdf_processor.PDFtoTextProcessor",
    "OCRMyPDF": "transaction_parser.transaction_parser.utils.pdf_processor.OCRMyPDFProcessor",
    "Docling": "transaction_parser.transaction_parser.utils.pdf_processor.DoclingPDFProcessor",
}


def get_pdf_processor(name: str | None = None) -> PDFProcessor:
    """
    Factory function to get a PDF processor by name.

    Resolution order:
    1. Check `pdf_processors` hook
    2. Fall back to built-in processors

    Usage:

    ```
    processor = get_pdf_processor("Docling")
    text = processor.process(file, page_limit=5)
    ```

    To register or override a processor from another app, add to its hooks.py:

    ```
    pdf_processors = {
        "MyProcessor": "my_app.utils.pdf_processor.MyPDFProcessor",
    }
    ```
    """
    if not name:
        name = (
            frappe.db.get_single_value("Transaction Parser Settings", "pdf_processor")
            or DEFAULT_PDF_PROCESSOR
        )

    # hooks override takes precedence
    hook_processors = frappe.get_hooks("pdf_processors") or {}
    class_path = (hook_processors.get(name) or [None])[-1]

    # fall back to built-in processors
    if not class_path:
        class_path = BUILTIN_PDF_PROCESSORS.get(name)

    if not class_path:
        available = get_available_pdf_processors()
        frappe.throw(
            title=_("Unsupported PDF Processor"),
            msg=_("PDF Processor '{0}' is not supported. <br>Choose from: {1}").format(
                name, ", ".join(available)
            ),
        )

    return frappe.get_attr(class_path)()


def get_available_pdf_processors() -> list[str]:
    """Return names of all registered PDF processors (built-in + hooks)."""
    hook_processors = frappe.get_hooks("pdf_processors") or {}
    return list({*BUILTIN_PDF_PROCESSORS, *hook_processors})
