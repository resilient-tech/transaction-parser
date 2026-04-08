# Copyright (c) 2026, Resilient Tech and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ParserBenchmarkLog(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        from transaction_parser.parser_benchmark.doctype.parser_benchmark_score_detail.parser_benchmark_score_detail import (
            ParserBenchmarkScoreDetail,
        )

        accuracy_score: DF.Percent
        ai_model: DF.Literal[
            "DeepSeek Chat",
            "DeepSeek Reasoner",
            "OpenAI gpt-4o",
            "OpenAI gpt-4o-mini",
            "OpenAI gpt-5",
            "OpenAI gpt-5-mini",
            "Google Gemini Pro-2.5",
            "Google Gemini Flash-2.5",
        ]
        ai_parse_time: DF.Float
        ai_response: DF.Code | None
        commit_hash: DF.Data | None
        commit_message: DF.SmallText | None
        company: DF.Link | None
        completion_tokens: DF.Int
        country: DF.Literal["India", "Other"]
        currency: DF.Link | None
        dataset: DF.Link
        error: DF.Code | None
        file_content: DF.Code | None
        file_parse_memory: DF.Float
        file_parse_time: DF.Float
        file_passed_to_ai: DF.Check
        input_cost: DF.Currency
        input_token_cost: DF.Currency
        naming_series: DF.Literal["PAR-BM-LOG-"]
        output_cost: DF.Currency
        output_token_cost: DF.Currency
        party: DF.DynamicLink | None
        party_type: DF.Link | None
        pdf_processor: DF.Literal["", "OCRMyPDF", "Docling"]
        prompt_tokens: DF.Int
        score_details: DF.Table[ParserBenchmarkScoreDetail]
        status: DF.Literal["Queued", "Running", "Completed", "Failed"]
        total_cost: DF.Currency
        total_time: DF.Float
        total_tokens: DF.Int
        transaction_type: DF.Literal["Sales Order", "Expense"]
    # end: auto-generated types

    def _get_dataset(self):
        if not self.dataset:
            return None

        if not hasattr(self, "_dataset_doc"):
            self._dataset_doc = frappe.get_cached_doc(
                "Parser Benchmark Dataset", self.dataset
            )

        return self._dataset_doc

    def get_from_dataset(self, fieldname: str):
        dataset = self._get_dataset()
        return dataset.get(fieldname) if dataset else None

    @property
    def transaction_type(self):
        return self.get_from_dataset("transaction_type")

    @property
    def country(self):
        return self.get_from_dataset("country")

    @property
    def company(self):
        return self.get_from_dataset("company")

    @property
    def party_type(self):
        return self.get_from_dataset("party_type")

    @property
    def party(self):
        return self.get_from_dataset("party")

    @property
    def page_limit(self):
        return self.get_from_dataset("page_limit") or 0
