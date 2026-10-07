"""Tests for parsing Communication attachments (automatic hook and manual Parse dialog)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from transaction_parser.transaction_parser.overrides.communication import (
    get_parse_defaults,
    on_update,
    parse_communication,
)

SETTINGS = "Transaction Parser Settings"
MODULE = "transaction_parser.transaction_parser.overrides.communication"

TO_EMAIL = "orders@tp-test.example.com"
CUSTOMER_EMAIL = "buyer@tp-test.example.com"
CUSTOMER = "_Test TP Customer"
SUPPLIER = "_Test TP Supplier"
COMPANY = "_Test Company"


def run_now(method, queue=None, now=None, **kwargs):
    frappe.get_attr(method)(**kwargs)


class TestCommunication(FrappeTestCase):
    def setUp(self):
        create_party("Customer", CUSTOMER)
        create_party("Supplier", SUPPLIER)

        settings = frappe.get_single(SETTINGS)
        settings.update(
            {
                "enabled": 1,
                "invoice_lookback_count": settings.invoice_lookback_count or 5,
                "default_ai_model": settings.default_ai_model or "OpenAI gpt-4o-mini",
                "parse_incoming_emails": 1,
                "parse_party_emails": 0,
                "process_one_document_per_communication": 0,
                "incoming_email_accounts": [],
                "party_emails": [],
            }
        )
        settings.append(
            "incoming_email_accounts",
            {
                "transaction": "Sales Order",
                "to_email": TO_EMAIL,
                "user": "Administrator",
                "company": COMPANY,
            },
        )
        settings.append(
            "party_emails",
            {
                "party_type": "Customer",
                "party": CUSTOMER,
                "party_email": CUSTOMER_EMAIL,
            },
        )
        settings.append(
            "party_emails",
            {
                "party_type": "Supplier",
                "party": SUPPLIER,
                "party_email": CUSTOMER_EMAIL,
            },
        )
        settings.save(ignore_permissions=True)
        self.settings = settings

        with patch("frappe.enqueue"):
            self.communication = create_communication()

        attach_files(
            self.communication,
            [
                "https://example.com/tp-test/invoice.pdf",
                "https://example.com/tp-test/items.XLSX",
                "https://example.com/tp-test/notes.txt",
            ],
        )

    def tearDown(self):
        frappe.db.rollback()
        frappe.clear_document_cache(SETTINGS, SETTINGS)

    # ----------------------
    # get_parse_defaults
    # ----------------------

    def test_defaults_from_matched_account(self):
        defaults = get_parse_defaults(self.communication.name)

        self.assertEqual(defaults["transaction"], "Sales Order")
        self.assertEqual(defaults["company"], COMPANY)
        self.assertEqual(
            defaults["parties"], {"Customer": CUSTOMER, "Supplier": SUPPLIER}
        )
        self.assertEqual(defaults["ai_model"], self.settings.default_ai_model)
        self.assertIn(self.settings.default_ai_model, defaults["supported_models"])
        self.assertEqual(defaults["process_one_document"], 0)
        self.assertEqual(defaults["is_processed"], 0)
        self.assertCountEqual(
            [a["file_url"] for a in defaults["attachments"]],
            [
                "https://example.com/tp-test/invoice.pdf",
                "https://example.com/tp-test/items.XLSX",
            ],
        )

    def test_defaults_transaction_from_party_email(self):
        frappe.db.set_value(
            "Transaction Parser Party Email",
            {"parent": SETTINGS, "party_type": "Customer"},
            "party_email",
            "someone-else@tp-test.example.com",
        )
        frappe.db.set_single_value(SETTINGS, "parse_party_emails", 1)
        frappe.clear_document_cache(SETTINGS, SETTINGS)

        defaults = get_parse_defaults(self.communication.name)

        # sender matches only the Supplier party email
        self.assertEqual(defaults["transaction"], "Expense")
        self.assertEqual(defaults["parties"], {"Customer": None, "Supplier": SUPPLIER})

    def test_defaults_without_matched_account(self):
        frappe.db.set_value(
            "Communication", self.communication.name, "recipients", "x@example.com"
        )

        defaults = get_parse_defaults(self.communication.name)

        self.assertIsNone(defaults["transaction"])
        self.assertEqual(
            defaults["company"], frappe.defaults.get_user_default("Company")
        )

    def test_defaults_throws_when_disabled(self):
        frappe.db.set_single_value(SETTINGS, "enabled", 0)
        frappe.clear_document_cache(SETTINGS, SETTINGS)

        self.assertRaises(
            frappe.ValidationError, get_parse_defaults, self.communication.name
        )

    # ----------------------
    # parse_communication
    # ----------------------

    # `_parse_attachments` commits after each document
    @patch("frappe.db.commit")
    @patch(f"{MODULE}._parse")
    @patch("frappe.enqueue", side_effect=run_now)
    def test_parse_each_attachment_separately(self, _enqueue, mock_parse, _commit):
        parse_communication(
            communication=self.communication.name,
            transaction="Expense",
            company=COMPANY,
            attachments=frappe.as_json(
                [
                    "https://example.com/tp-test/invoice.pdf",
                    "https://example.com/tp-test/items.XLSX",
                ]
            ),
            party=SUPPLIER,
            ai_model="OpenAI gpt-4o",
            page_limit="2",
            process_one_document=0,
        )

        self.assertEqual(mock_parse.call_count, 2)
        kwargs = mock_parse.call_args_list[0].kwargs
        self.assertEqual(kwargs["transaction"], "Expense")
        self.assertEqual(kwargs["file_urls"], "https://example.com/tp-test/invoice.pdf")
        self.assertEqual(kwargs["company"], COMPANY)
        self.assertEqual(kwargs["party"], SUPPLIER)
        self.assertEqual(kwargs["ai_model"], "OpenAI gpt-4o")
        self.assertEqual(kwargs["page_limit"], 2)
        self.assertEqual(kwargs["user"], frappe.session.user)

        self.assertEqual(
            frappe.db.get_value(
                "Communication",
                self.communication.name,
                "is_processed_by_transaction_parser",
            ),
            1,
        )

    # `_parse_attachments` commits after each document
    @patch("frappe.db.commit")
    @patch(f"{MODULE}._parse")
    @patch("frappe.enqueue", side_effect=run_now)
    def test_parse_combined_into_one_document(self, _enqueue, mock_parse, _commit):
        parse_communication(
            communication=self.communication.name,
            transaction="Sales Order",
            company=COMPANY,
            attachments=[
                "https://example.com/tp-test/invoice.pdf",
                "https://example.com/tp-test/items.XLSX",
            ],
            process_one_document=1,
        )

        mock_parse.assert_called_once()
        kwargs = mock_parse.call_args.kwargs
        self.assertCountEqual(
            kwargs["file_urls"],
            [
                "https://example.com/tp-test/invoice.pdf",
                "https://example.com/tp-test/items.XLSX",
            ],
        )
        self.assertIsNone(kwargs["party"])
        self.assertIsNone(kwargs["page_limit"])

    @patch("frappe.enqueue")
    def test_parse_rejects_invalid_attachments(self, mock_enqueue):
        for attachments in (
            [],
            ["https://example.com/tp-test/notes.txt"],
            ["https://example.com/not-attached.pdf"],
        ):
            with self.subTest(attachments=attachments):
                self.assertRaises(
                    frappe.ValidationError,
                    parse_communication,
                    communication=self.communication.name,
                    transaction="Sales Order",
                    company=COMPANY,
                    attachments=attachments,
                )

        mock_enqueue.assert_not_called()

    # ----------------------
    # on_update (automatic parsing)
    # ----------------------

    @patch("frappe.enqueue")
    def test_on_update_enqueues_matched_account(self, mock_enqueue):
        on_update(self.communication)

        mock_enqueue.assert_called_once()
        kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(kwargs["transaction_type"], "Sales Order")
        self.assertEqual(kwargs["user"], "Administrator")
        self.assertEqual(kwargs["party"], CUSTOMER)
        self.assertEqual(kwargs["company"], COMPANY)
        self.assertEqual(kwargs["ai_model"], self.settings.default_ai_model)
        self.assertEqual(len(kwargs["attachments"]), 2)
        self.assertNotIn("process_one_document", kwargs)

    @patch("frappe.enqueue")
    def test_on_update_party_email_decides_transaction(self, mock_enqueue):
        frappe.db.set_single_value(SETTINGS, "parse_party_emails", 1)
        frappe.clear_document_cache(SETTINGS, SETTINGS)

        on_update(self.communication)

        kwargs = mock_enqueue.call_args.kwargs
        # first matching party email row is the Customer
        self.assertEqual(kwargs["transaction_type"], "Sales Order")
        self.assertEqual(kwargs["party"], CUSTOMER)
        self.assertEqual(kwargs["user"], frappe.session.user)


def create_party(party_type, party_name):
    if frappe.db.exists(party_type, party_name):
        return

    group_doctype = f"{party_type} Group"
    group_field = frappe.scrub(group_doctype)

    frappe.get_doc(
        {
            "doctype": party_type,
            frappe.scrub(f"{party_type} Name"): party_name,
            group_field: frappe.db.get_value(group_doctype, {"is_group": 0}),
        }
    ).insert(ignore_permissions=True)


def create_communication():
    return frappe.get_doc(
        {
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Email",
            "sent_or_received": "Received",
            "subject": "Purchase order",
            "content": "Please find attached",
            "sender": CUSTOMER_EMAIL,
            "recipients": TO_EMAIL,
        }
    ).insert(ignore_permissions=True)


def attach_files(communication, file_urls):
    for file_url in file_urls:
        frappe.get_doc(
            {
                "doctype": "File",
                "file_url": file_url,
                "file_name": file_url.rsplit("/", 1)[-1],
                "attached_to_doctype": "Communication",
                "attached_to_name": communication.name,
            }
        ).insert(ignore_permissions=True)
