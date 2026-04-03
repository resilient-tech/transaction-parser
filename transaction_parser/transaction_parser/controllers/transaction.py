import erpnext
import frappe
from erpnext.setup.utils import get_exchange_rate
from erpnext.stock.get_item_details import get_item_details
from httpx import HTTPError
from rapidfuzz import fuzz, process

from transaction_parser.exceptions import FileProcessingError
from transaction_parser.transaction_parser.ai_integration.parser import AIParser
from transaction_parser.transaction_parser.utils import to_dict
from transaction_parser.transaction_parser.utils.file_processor import FileProcessor
from transaction_parser.transaction_parser.utils.response_merger import (
    ResponseMerger,
)


class Transaction:
    """Base class for transaction document processing and generation."""

    DOCTYPE = None
    PARTY_DOCTYPE = None

    def __init__(
        self, settings=None, party: str | None = None, company: str | None = None
    ):
        if not self.DOCTYPE:
            raise NotImplementedError("DOCTYPE is not defined")

        if not self.PARTY_DOCTYPE:
            raise NotImplementedError("PARTY_DOCTYPE is not defined")

        self.settings = settings or frappe.get_cached_doc("Transaction Parser Settings")
        self.party = party
        self.company = company

    def generate(
        self,
        files,
        ai_model: str | None = None,
        page_limit: int | None = None,
    ):
        self.initialize()

        if isinstance(files, str):
            files = [files]

        self.files = files
        self.ai_model = ai_model
        self.data = self._parse_file_content(ai_model, page_limit)
        self.doc = frappe.get_doc({"doctype": self.DOCTYPE})
        self.doc.is_created_by_transaction_parser = 1

        self.set_details()
        self.set_missing_values()
        self._set_flags()
        self.doc.insert()
        self._attach_file()

        return self.doc

    def initialize(self) -> None:
        # file processing
        self.files = None

        # output schema
        self.schema = None
        self.document_schema = None
        self.tax_schema = None
        self.address_schema = None
        self.party_schema = None
        self.item_schema = None

        # data mapping
        self.data = None

        # draft document
        self.doc = None

    #####################################
    ########## File Processing ##########
    #####################################

    def _parse_file_content(
        self, ai_model: str | None = None, page_limit: int | None = None
    ) -> dict:
        if len(self.files) > 1:
            return self._parse_multiple_files(ai_model, page_limit)

        return self._parse_single_file(self.files[0], ai_model, page_limit)

    def _parse_single_file(
        self,
        file,
        ai_model: str | None = None,
        page_limit: int | None = None,
    ) -> dict:
        try:
            content = FileProcessor().get_content(file, page_limit)
            schema = self.get_schema()

            return AIParser(ai_model, self.settings).parse(
                document_type=self.DOCTYPE,
                document_schema=schema,
                document_data=content,
                doc_name=file.name,
            )

        except FileProcessingError as e:
            error_log = frappe.log_error(
                title="File processing error in Transaction Parser",
                reference_doctype="File",
                reference_name=file.name,
            )
            e.error_log = error_log
            raise e

        except HTTPError as e:
            error_log = frappe.log_error(
                title="Transaction Parser API error",
                reference_doctype="File",
                reference_name=file.name,
            )
            e.error_log = error_log
            raise e

    def _parse_multiple_files(
        self, ai_model: str | None = None, page_limit: int | None = None
    ) -> dict:
        response = self._parse_single_file(self.files[0], ai_model, page_limit)
        merger = ResponseMerger(
            response,
            schema=self.get_schema(),
            match_keys=self.get_match_keys(),
        )

        for file in self.files[1:]:
            if merger.is_complete():
                break

            new_response = self._parse_single_file(file, ai_model, page_limit)
            merger.merge(new_response)

        return merger.response

    ###################################
    ########## Output Schema ##########
    ###################################

    def get_match_keys(self) -> dict[str, list[str]]:
        """Return list field name -> key fields used to match items during merge."""
        return {
            "item_list": ["party_item_code", "quantity", "rate", "description"],
        }

    def get_schema(self) -> dict:
        if not self.schema:
            self.schema = self._get_schema()

        return self.schema

    def _get_schema(self) -> dict:
        return {
            **self.get_default_schema(),
            **self.get_custom_schema(),
        }

    def get_default_schema(self) -> dict:
        return {
            "document_number": "string (unique identifier)",
            "document_date": "date | null",
            "currency": "ISO currency code (e.g., INR, USD, etc.)",
            "item_list": [self.get_item_schema()],
            "totals": {
                "subtotal": "float",
                "taxes": [self.get_tax_schema()],
                "total_tax_percentage": "float | null",
                "total_tax_amount": "float | null",
                "grand_total": "float",
            },
            "payment_terms": [
                {
                    "credit_days": "int | null",
                    "credit_from": "string | null",
                    "due_date": "date | null",
                    "invoice_portion": "float | null (percentage of invoice)",
                }
            ],
            "local_terms": {
                "incoterms": "string (e.g., EXW, DDP, etc.)",
                "description": "string",
            },
        }

    def get_custom_schema(self) -> dict:
        return to_dict(self.settings.base_schema, throw=False)

    ### Item

    def get_item_schema(self) -> dict:
        if not self.item_schema:
            self.item_schema = self._get_item_schema()

        return self.item_schema

    def _get_item_schema(self) -> dict:
        return {
            **self.get_default_item_schema(),
            **self.get_custom_item_schema(),
        }

    def get_default_item_schema(self) -> dict:
        return {
            "serial_number": "string | null",
            "party_item_code": "string | null (Dont confuse this with serial number)",
            "description": "string",
            "quantity": "float",
            "unit": "string (e.g., KG, MTR, PC, etc.)",
            "rate": "float",
            "amount": "float (sometimes called `net amount`)",
            "discount": "float | 0",
            "taxes": [self.get_tax_schema()],
            "total_tax_percentage": "float | null",
            "total_tax_amount": "float | null",
            "is_price_inclusive_of_taxes": "boolean",
            "delivery_date": "date | null",
        }

    def get_custom_item_schema(self) -> dict:
        return to_dict(self.settings.item_schema, throw=False)

    ### Tax

    def get_tax_schema(self) -> dict:
        if not self.tax_schema:
            self.tax_schema = self._get_tax_schema()

        return self.tax_schema

    def _get_tax_schema(self) -> dict:
        return {
            **self.get_default_tax_schema(),
            **self.get_custom_tax_schema(),
        }

    def get_default_tax_schema(self) -> dict:
        return {
            "description": "string",
            "percentage": "float",
            "amount": "float",
        }

    def get_custom_tax_schema(self) -> dict:
        return to_dict(self.settings.tax_schema, throw=False)

    ### Party

    def get_party_schema(self) -> dict:
        if not self.party_schema:
            self.party_schema = self._get_party_schema()

        return self.party_schema

    def _get_party_schema(self) -> dict:
        return {
            **self.get_default_party_schema(),
            **self.get_custom_party_schema(),
        }

    def get_default_party_schema(self) -> dict:
        return {
            "name": "string",
            "address": self.get_address_schema(),
            "contact": {
                "email": ["string"],
                "phone": ["string"],
            },
        }

    def get_custom_party_schema(self) -> dict:
        return to_dict(self.settings.party_schema, throw=False)

    ### Address

    def get_address_schema(self) -> dict:
        if not self.address_schema:
            self.address_schema = self._get_address_schema()

        return self.address_schema

    def _get_address_schema(self) -> dict:
        return {
            **self.get_default_address_schema(),
            **self.get_custom_address_schema(),
        }

    def get_default_address_schema(self) -> dict:
        return {
            "address_line_1": "string",
            "address_line_2": "string",
            "city": "string",
            "state": "string",
            "postal_code": "string",
            "country": "ISO country code (e.g., IN, US, etc.)",
        }

    def get_custom_address_schema(self) -> dict:
        return to_dict(self.settings.address_schema, throw=False)

    # Item Expense Account Mapping Schema

    def get_expense_account_schema(self) -> list:
        return [
            {
                "expense_account": "string (Expense Account name)",
                "item_description": "string (Item codes that map to this expense account)",
            }
        ]

    ##################################
    ########## Data Mapping ##########
    ##################################

    def set_details(self):
        raise NotImplementedError(
            "set_details() method must be implemented by subclass"
        )

    def set_missing_values(self):
        raise NotImplementedError(
            "set_missing_values() method must be implemented by subclass"
        )

    def _set_flags(self) -> None:
        self.doc.flags.ignore_permissions = True
        self.doc.flags.ignore_mandatory = True
        self.doc.flags.ignore_validate = True
        self.doc.flags.ignore_links = True

    def _attach_file(self) -> None:
        files_to_attach = self.files if isinstance(self.files, list) else [self.files]

        for file_doc in files_to_attach:
            file_doc.attached_to_doctype = self.DOCTYPE
            file_doc.attached_to_name = self.doc.name
            file_doc.save()

    def set_exchange_rate(self, from_currency, date, args):
        company_currency = erpnext.get_company_currency(self.doc.company)
        if not self.doc.currency or self.doc.currency == company_currency:
            self.doc.currency = company_currency
            self.doc.conversion_rate = 1.0
        else:
            self.doc.conversion_rate = get_exchange_rate(
                from_currency,
                company_currency,
                date,
                args,
            )

    ### Party

    def search_party(
        self, party, party_type: str, fieldname: str = "name"
    ) -> str | None:
        return frappe.db.exists(party_type, {fieldname: party.name})

    def guess_party(
        self, party, party_type: str, party_names: list | None = None
    ) -> str | None:
        if not party_names:
            party_names = frappe.get_all(party_type, pluck="name")

        return self.guess_value(party.name, party_names)

    def guess_value(
        self, value: str, options: list | dict, score_cutoff: int = 75
    ) -> str | None:
        # When `options` is a list:
        #   extractOne("abcd", ["value1", "value2"])
        #   Output: ("value1", 1, 0)

        # When `options` is a dictionary:
        #   extractOne("abcd", {"key": "value"})
        #   Output: ("value", 75.0, "key")
        if result := process.extractOne(
            value, options, score_cutoff=score_cutoff, scorer=fuzz.token_set_ratio
        ):
            if isinstance(options, dict):
                return result[2]
            return result[0]

    ### Address

    def get_address(self, party, party_type: str, address) -> str | None:
        address_doctype = frappe.qb.DocType("Address")
        link_doctype = frappe.qb.DocType("Dynamic Link")

        erp_addresses = (
            frappe.qb.from_(address_doctype)
            .join(link_doctype)
            .on(address_doctype.name == link_doctype.parent)
            .select(
                address_doctype.name,
                address_doctype.address_line1,
                address_doctype.pincode,
            )
            .where(link_doctype.link_doctype == party_type)
            .where(link_doctype.link_name == party.name)
        ).run(as_dict=True)

        if found := self.search_address(party, address, erp_addresses):
            return found

        return self.guess_address(party, address, erp_addresses)

    def search_address(self, party, address, erp_addresses) -> str | None:
        pincode_match = None
        address_line1_match = None

        for erp_address in erp_addresses:
            is_pincode_match = (
                erp_address.pincode and erp_address.pincode == address.postal_code
            )

            is_address_line1_match = (
                erp_address.address_line1
                and erp_address.address_line1 == address.address_line_1
            )

            if is_pincode_match and is_address_line1_match:
                return erp_address.name

            if not pincode_match and is_pincode_match:
                pincode_match = erp_address.name

            if not address_line1_match and is_address_line1_match:
                address_line1_match = erp_address.name

        return pincode_match or address_line1_match

    def guess_address(self, party, address, erp_addresses: list) -> str | None:
        address_line_1_map = {
            erp_address.address_line1: erp_address.name for erp_address in erp_addresses
        }

        if found := self.guess_value(address.address_line_1, address_line_1_map.keys()):
            return address_line_1_map.get(found)

    ### Item

    def get_item(self, item, item_code: str | None, **kwargs) -> frappe._dict:
        item_details = {}

        if item_code and self.doc.company and self.doc.currency:
            item_details = get_item_details(
                {
                    **kwargs,
                    "item_code": item_code,
                    "company": self.doc.company,
                    "currency": self.doc.currency,
                    "doctype": self.DOCTYPE,
                }
            )

        self.process_item_details(item, item_details)

        if item.discount:
            self.doc.discount_amount = (self.doc.discount_amount or 0) + item.discount

        return frappe._dict(
            {
                **item_details,
                **item,
                "qty": item.quantity,
                "rate": item.rate or item_details.get("price_list_rate", 0),
            }
        )

    def process_item_details(self, item, item_details) -> None:
        """Process item details fetched from get_item_details"""
        pass

    ### Payment Schedule

    def get_payment_schedule(self) -> list:
        return [self.get_payment_schedule_doc(term) for term in self.data.payment_terms]

    def get_payment_schedule_doc(self, term):
        return frappe.get_doc(
            {
                "doctype": "Payment Schedule",
                "parentfield": "payment_schedule",
                **term,
                "description": (
                    f"{term.credit_days} days from {term.credit_from}"
                    if term.credit_days and term.credit_from
                    else None
                ),
                "payment_amount": (
                    total * portion / 100
                    if (total := self.data.totals.grand_total)
                    and (portion := term.invoice_portion)
                    else None
                ),
            }
        )

    ### Terms and Conditions

    def get_terms(self) -> str:
        terms = (
            description if (description := self.data.local_terms.description) else ""
        )

        if incoterms := self.data.local_terms.incoterms:
            terms += f"\nIncoterms: {incoterms}"

        return terms

    ### Contact

    def get_contact(self, emails: list, phones: list) -> str | None:
        if emails and (
            found := frappe.db.get_value(
                "Contact Email", {"email_id": ["in", emails]}, "parent"
            )
        ):
            return found

        if phones and (
            found := frappe.db.get_value(
                "Contact Phone", {"phone": ["in", phones]}, "parent"
            )
        ):
            return found
