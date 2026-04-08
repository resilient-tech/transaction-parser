# Copyright (c) 2026, Resilient Tech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# Maps dataset checkbox fieldnames → model/processor display names
AI_MODEL_FIELD_MAP = {
    "deepseek_chat": "DeepSeek Chat",
    "deepseek_reasoner": "DeepSeek Reasoner",
    "openai_gpt_4o": "OpenAI gpt-4o",
    "openai_gpt_4o_mini": "OpenAI gpt-4o-mini",
    "openai_gpt_5": "OpenAI gpt-5",
    "openai_gpt_5_mini": "OpenAI gpt-5-mini",
    "google_gemini_pro_25": "Google Gemini Pro-2.5",
    "google_gemini_flash_25": "Google Gemini Flash-2.5",
}

PDF_PROCESSOR_FIELD_MAP = {
    "ocrmypdf": "OCRMyPDF",
    "docling": "Docling",
}

DOCTYPE = "Parser Benchmark Dataset"


class ParserBenchmarkDataset(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        from transaction_parser.parser_benchmark.doctype.parser_benchmark_dataset_file.parser_benchmark_dataset_file import (
            ParserBenchmarkDatasetFile,
        )
        from transaction_parser.parser_benchmark.doctype.parser_benchmark_expected_field.parser_benchmark_expected_field import (
            ParserBenchmarkExpectedField,
        )

        amended_from: DF.Link | None
        company: DF.Link | None
        country: DF.Literal["India", "Other"]
        deepseek_chat: DF.Check
        deepseek_reasoner: DF.Check
        docling: DF.Check
        enabled: DF.Check
        expected_fields: DF.Table[ParserBenchmarkExpectedField]
        files: DF.Table[ParserBenchmarkDatasetFile]
        google_gemini_flash_25: DF.Check
        google_gemini_pro_25: DF.Check
        is_multiple_files: DF.Check
        naming_series: DF.Literal["PAR-BM-DTS-"]
        ocrmypdf: DF.Check
        openai_gpt_4o: DF.Check
        openai_gpt_4o_mini: DF.Check
        openai_gpt_5: DF.Check
        openai_gpt_5_mini: DF.Check
        page_limit: DF.Int
        party: DF.DynamicLink | None
        party_type: DF.Link | None
        pass_file_to_ai: DF.Check
        transaction_type: DF.Literal["Sales Order", "Expense"]
    # end: auto-generated types

    SUPPORTED_FILE_TYPES = ("PDF", "CSV", "XLSX", "XLS")

    def validate(self):
        self.validate_files()
        self.validate_selected_models()
        self.validate_expected_fields()

    def before_update_after_submit(self):
        self.validate_files()

    def validate_files(self):
        """Set file_type for each row and auto-set is_multiple_files."""
        for row in self.files:
            if row.file and (not row.file_type or row.has_value_changed("file")):
                file_doc = frappe.get_last_doc("File", filters={"file_url": row.file})
                row.file_type = file_doc.file_type

                if row.file_type not in self.SUPPORTED_FILE_TYPES:
                    frappe.throw(
                        _(
                            "File '{0}' has unsupported type '{1}'. Supported types are:<br>{2}."
                        ).format(
                            file_doc.file_name,
                            row.file_type,
                            "<br>".join(self.SUPPORTED_FILE_TYPES),
                        )
                    )

        self.is_multiple_files = len(self.files) > 1

    def validate_selected_models(self):
        if not self.get_selected_models():
            frappe.throw(_("Please select at least one AI Model."))

    def validate_expected_fields(self):
        if not self.expected_fields:
            return

        seen_keys = set()
        for row in self.expected_fields:
            if row.key in seen_keys:
                frappe.throw(
                    _("Duplicate key '{0}' in Expected Fields row {1}").format(
                        row.key, row.idx
                    )
                )
            seen_keys.add(row.key)

            try:
                frappe.parse_json(row.expected_json)
            except Exception:
                frappe.throw(
                    title=_("Invalid JSON"),
                    msg=_(
                        "Expected JSON in row {0} (key: {1}) must be valid JSON."
                    ).format(row.idx, row.key),
                )

    def get_selected_models(self) -> list[str]:
        """Return list of selected AI model names."""
        return [label for field, label in AI_MODEL_FIELD_MAP.items() if self.get(field)]

    def get_selected_processors(self) -> list[str]:
        """Return list of selected PDF processor names."""
        return [
            label for field, label in PDF_PROCESSOR_FIELD_MAP.items() if self.get(field)
        ]

    def has_pdf_file(self) -> bool:
        """Check if any file in the child table is a PDF."""
        return any(row.file_type == "PDF" for row in self.files)

    def get_file_docs(self) -> list:
        """Return File documents for each row in the files child table."""
        file_docs = []
        for row in self.files:
            file_doc = frappe.get_last_doc("File", filters={"file_url": row.file})
            file_docs.append(file_doc)
        return file_docs


@frappe.whitelist()
def run_benchmark(dataset_name: str):
    """Create Benchmark Logs for each model x processor combo and enqueue runs."""
    frappe.has_permission(DOCTYPE, "write", throw=True)

    if frappe.db.get_value(DOCTYPE, dataset_name, "docstatus") != 1:
        frappe.throw(_("Dataset must be submitted before running benchmarks."))

    log_names = create_and_enqueue_benchmark_logs(dataset_name)

    if not log_names:
        frappe.throw(
            _(
                "No new benchmarks to queue. Please check if the dataset is properly configured"
            )
        )

    return log_names


def create_and_enqueue_benchmark_logs(dataset_name: str) -> list[str]:
    """Create one log per model x processor combo and enqueue each for background execution."""
    dataset: ParserBenchmarkDataset = frappe.get_cached_doc(DOCTYPE, dataset_name)
    models = dataset.get_selected_models()

    if dataset.pass_file_to_ai:
        processors = [None]
    elif dataset.has_pdf_file():
        processors = dataset.get_selected_processors() or [None]
    else:
        processors = [None]

    commit_info = get_commit_info()
    log_names = []

    for ai_model in models:
        for pdf_processor in processors:
            log = frappe.new_doc("Parser Benchmark Log")
            log.update(
                {
                    "status": "Queued",
                    "dataset": dataset.name,
                    "ai_model": ai_model,
                    "pdf_processor": pdf_processor,
                    "currency": "USD",
                    **commit_info,
                }
            )
            log.insert(ignore_permissions=True)
            log_names.append(log.name)

    # commit before enqueuing so background jobs can read the inserted logs
    frappe.db.commit()  # nosemgrep

    for log_name in log_names:
        try:
            frappe.enqueue(
                _run_benchmark,
                log_name=log_name,
                queue="long",
            )
        except Exception:
            frappe.db.set_value("Parser Benchmark Log", log_name, "status", "Failed")
            frappe.db.commit()  # nosemgrep -- persist Failed status when enqueue fails

    return log_names


def _run_benchmark(log_name: str):
    from transaction_parser.parser_benchmark.runner import BenchmarkRunner

    BenchmarkRunner(log_name).run()


def get_commit_info() -> dict:
    """Return the current git commit hash and message for the transaction_parser app."""
    import subprocess

    app_path = frappe.get_app_path("transaction_parser")

    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H%n%s"],
            cwd=app_path,
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n", 1)
            return {
                "commit_hash": lines[0] if lines else "",
                "commit_message": lines[1] if len(lines) > 1 else "",
            }
    except Exception:
        pass

    return {}
