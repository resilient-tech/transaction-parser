import frappe

from transaction_parser.transaction_parser.utils.pdf_processor import (
    DEFAULT_PDF_PROCESSOR,
)


def execute():
    frappe.db.set_single_value(
        "Transaction Parser Settings", "pdf_processor", DEFAULT_PDF_PROCESSOR
    )
