# Copyright (c) 2025, Resilient Tech and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document

from transaction_parser.transaction_parser.utils import to_dict

DOCTYPE = "Transaction Parser Settings"


class TransactionParserSettings(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        from transaction_parser.transaction_parser.doctype.transaction_parser_api_key_item.transaction_parser_api_key_item import (
            TransactionParserAPIKeyItem,
        )
        from transaction_parser.transaction_parser.doctype.transaction_parser_email_account.transaction_parser_email_account import (
            TransactionParserEmailAccount,
        )
        from transaction_parser.transaction_parser.doctype.transaction_parser_party_email.transaction_parser_party_email import (
            TransactionParserPartyEmail,
        )

        address_schema: DF.JSON | None
        api_keys: DF.Table[TransactionParserAPIKeyItem]
        base_schema: DF.JSON | None
        default_ai_model: DF.Literal[
            "DeepSeek Chat",
            "DeepSeek Reasoner",
            "OpenAI gpt-4o",
            "OpenAI gpt-4o-mini",
            "OpenAI gpt-5",
            "OpenAI gpt-5-mini",
            "Google Gemini Pro-2.5",
            "Google Gemini Flash-2.5",
        ]
        enabled: DF.Check
        incoming_email_accounts: DF.Table[TransactionParserEmailAccount]
        invoice_lookback_count: DF.Int
        item_schema: DF.JSON | None
        pass_file_to_ai: DF.Check
        parse_incoming_emails: DF.Check
        parse_party_emails: DF.Check
        party_emails: DF.Table[TransactionParserPartyEmail]
        party_schema: DF.JSON | None
        pdf_processor: DF.Literal["OCRMyPDF", "Docling"]
        process_one_document_per_communication: DF.Check
        tax_schema: DF.JSON | None

    # end: auto-generated types
    # TODO: can we check API creds?
    def validate(self):
        self.validate_lookback_count()
        self.validate_incoming_email_accounts()
        self.validate_party_email()
        self.validate_json_fields()

    def validate_lookback_count(self):
        if self.invoice_lookback_count <= 0:
            frappe.throw(
                _("{0} must be greater than 0.").format(
                    frappe.bold(self.meta.get_label("invoice_lookback_count"))
                )
            )

    def validate_incoming_email_accounts(self):
        if not self.parse_incoming_emails:
            return

        email_accounts = set()
        for row in self.incoming_email_accounts:
            if row.to_email in email_accounts:
                frappe.throw(
                    _(
                        "Row #{0}: Duplicate email account {1} in incoming email accounts."
                    ).format(row.idx, row.to_email)
                )

            email_accounts.add(row.to_email)

    def validate_party_email(self):
        if not self.parse_incoming_emails:
            return

        party_email_map = {}

        for row in self.party_emails:
            if row.party_type not in party_email_map:
                party_email_map[row.party_type] = set()

            if row.party_email in party_email_map[row.party_type]:
                frappe.throw(
                    _("Row #{0}: Duplicate email {1} for party type {2}.").format(
                        row.idx,
                        frappe.bold(row.party_email),
                        frappe.bold(row.party_type),
                    )
                )

            party_email_map[row.party_type].add(row.party_email)

    def validate_json_fields(self):
        for field in self.meta.fields:
            self._validate_json_field(field)

    def _validate_json_field(self, field):
        if field.fieldtype != "JSON":
            return

        value = self.get(field.fieldname)
        if not value:
            return

        try:
            to_dict(value)
        except Exception:
            frappe.clear_last_message()
            frappe.throw(
                _("Please provide a valid JSON value for {0}").format(
                    frappe.bold(field.label)
                )
            )


@frappe.whitelist()
def get_ai_models():
    default_model = frappe.get_cached_value(DOCTYPE, None, "default_ai_model")
    supported_models = frappe.get_meta(DOCTYPE).get_field("default_ai_model").options

    return {
        "default_model": default_model,
        "supported_models": supported_models,
    }
