import frappe


class FileProcessingError(frappe.ValidationError):
    """Custom exception for file processing errors."""
