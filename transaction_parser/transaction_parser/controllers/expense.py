from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import Criterion

from transaction_parser.transaction_parser.ai_integration.parser import AIParser
from transaction_parser.transaction_parser.ai_integration.prompts import (
    get_expense_account_system_prompt,
    get_expense_account_user_prompt,
)
from transaction_parser.transaction_parser.controllers.transaction import Transaction

ACCOUNT_FIELDNAME_MAP = {
    "CGST": "cgst_account",
    "SGST": "sgst_account",
    "IGST": "igst_account",
}


class Expense(Transaction):
    """Expense transaction processor for Purchase Invoices."""

    DOCTYPE = "Purchase Invoice"
    PARTY_DOCTYPE = "Supplier"

    ###################################
    ########## Output Schema ##########
    ###################################

    def get_default_schema(self) -> dict:
        return {
            **super().get_default_schema(),
            "purchase_order_date": "date | null (Also called `Order Date`. It can be different than Document Date)",
            "purchase_order_number": "string | null (Purchase Order number if available)",
            "company": {
                "shipping": self.get_party_schema(),
                "billing": self.get_party_schema(),
            },
            "supplier": self.get_party_schema(),
        }

    ##################################
    ########## Data Mapping ##########
    ##################################

    def set_details(self) -> None:
        self.doc.company = self.get_company()
        if not self.doc.company:
            frappe.throw(_("Company not found"))

        self.doc.supplier = self.get_supplier()

        self.doc.bill_no = self.data.document_number

        if existing_invoice := frappe.db.exists(
            "Purchase Invoice", {"bill_no": self.doc.bill_no, "docstatus": 1}
        ):
            frappe.throw(
                _(
                    "Duplicate Purchase Invoice {existing_invoice} found with Bill number {bill_no}"
                ).format(existing_invoice=existing_invoice, bill_no=self.doc.bill_no)
            )

        self.doc.bill_date = self.data.purchase_order_date
        self.doc.currency = self.data.currency or None

        self.set_exchange_rate(self.doc.currency, self.doc.posting_date, "for_buying")

        self.doc.billing_address = self.get_company_billing_address()
        self.doc.shipping_address = self.get_company_shipping_address()
        self.doc.supplier_address = self.get_supplier_address()

        self.doc.contact_person = self.get_party_contact(
            self.data.company.billing, self.data.company.shipping
        )

        self.set_item_tax_template()
        self.doc.items = self.get_items()
        self.set_expense_accounts()
        self.doc.terms = self.get_terms()

    def set_missing_values(self) -> None:
        self.doc.set_missing_values()
        self.doc.calculate_taxes_and_totals()

    def get_company(self) -> str | None:
        self.company_found_against = "company"
        if self.company:
            return self.company

        party_type = "Company"
        fieldname = "name"

        company_identification_order = (
            ("company", self.data.company.billing),
            ("company", self.data.company.shipping),
            ("supplier", self.data.supplier),
        )

        # search
        for key, party in company_identification_order:
            if not party:
                continue

            if found := self.search_party(party, party_type, fieldname):
                self.company_found_against = key
                return found

        # guess
        party_names = frappe.get_all(party_type, pluck="name")
        for key, party in company_identification_order:
            if not party:
                continue

            if found := self.guess_party(party, party_type, party_names):
                self.company_found_against = key
                return found

    def get_supplier(self) -> str | None:
        self.supplier_found_against = "supplier"
        if self.party:
            return self.party

        party_type = "Supplier"
        fieldname = "supplier_name"

        supplier_identification_order = (
            ("supplier", self.data.supplier),
            ("company", self.data.company.billing),
            ("company", self.data.company.shipping),
        )

        # search
        for key, party in supplier_identification_order:
            if not party or key == self.company_found_against:
                continue

            if found := self.search_party(party, party_type, fieldname):
                self.supplier_found_against = key
                return found

        # guess
        party_names = dict(
            frappe.get_all(party_type, fields=["name", fieldname], as_list=True)
        )
        for key, party in supplier_identification_order:
            if not party or key == self.company_found_against:
                continue

            if found := self.guess_party(party, party_type, party_names):
                self.supplier_found_against = key
                return found

    def get_company_billing_address(self):
        return self._get_company_address("billing")

    def get_company_shipping_address(self):
        return self._get_company_address("shipping")

    def _get_company_address(self, address_type: str):
        address_details = (
            getattr(self.data.company, address_type)
            if self.company_found_against == "company"
            else self.data.supplier
        )

        if not address_details:
            return None

        return self.get_address(
            frappe._dict({**address_details, "name": self.doc.company}),
            "Company",
            address_details,
        )

    def get_supplier_address(self):
        supplier_address_details = (
            (self.data.supplier,)
            if self.supplier_found_against == "supplier"
            else (self.data.company.billing, self.data.company.shipping)
        )

        # Filter out None values
        supplier_address_details = [d for d in supplier_address_details if d]

        for detail in supplier_address_details:
            if found := self.get_address(
                frappe._dict({**detail, "name": self.doc.supplier}),
                "Supplier",
                detail,
            ):
                return found

    def get_items(self) -> list:
        if not self.data.item_list:
            return []

        items = []
        mapped_indices = set()
        is_price_inclusive_of_taxes = any(
            item.is_price_inclusive_of_taxes for item in self.data.item_list
        )
        self.doc.apply_discount_on = (
            "Grand Total" if is_price_inclusive_of_taxes else "Net Total"
        )
        # Try mapping using Purchase Order if available
        po_number = self.data.purchase_order_number
        if po_number:
            self.map_purchase_order_items(po_number, items, mapped_indices)

        latest_items = self.get_latest_items(self.doc.supplier)

        # For remaining items, try matching with latest items
        for index, item in enumerate(self.data.item_list):
            if index in mapped_indices:
                continue

            choices = {row.item_code: row.description for row in latest_items}
            expense_account_map = {
                row.item_code: row.expense_account for row in latest_items
            }

            if choices:
                matched_item_code = self.guess_value(item.description, choices)
                if matched_item_code:
                    items.append(
                        self.get_item(
                            item,
                            matched_item_code,
                            expense_account=expense_account_map.get(matched_item_code),
                            item_tax_template=item.item_tax_template,
                        )
                    )
                    continue

            # If no match, just use description, rate, qty
            items.append(
                self.get_item(
                    item,
                    None,
                    expense_account=None,
                    item_tax_template=item.item_tax_template,
                )
            )

        return items

    def map_purchase_order_items(
        self, po_number: str, items: list, mapped_indices: set
    ) -> None:
        """Map items from Purchase Order."""
        if not frappe.db.exists("Purchase Order", po_number):
            return

        po = frappe.get_doc("Purchase Order", po_number)
        if po.company != self.doc.company:
            return

        for index, item in enumerate(self.data.item_list):
            for po_item in po.items:
                if po_item.get("mapped"):
                    continue

                if (
                    abs(item.rate - po_item.rate) < 0.01
                    and abs(item.quantity - po_item.qty) < 0.01
                ):
                    items.append(
                        self.get_item(
                            item,
                            po_item.item_code,
                            expense_account=po_item.expense_account,
                            purchase_order=po.name,
                            item_tax_template=item.item_tax_template,
                        )
                    )
                    mapped_indices.add(index)
                    po_item.mapped = True
                    break

    def get_latest_items(self, supplier):
        invoices = frappe.get_all(
            "Purchase Invoice",
            filters={"supplier": supplier, "docstatus": 1},
            limit=self.settings.invoice_lookback_count,
            pluck="name",
        )
        if not invoices:
            return []

        PURCHASE_INVOICE_ITEM = frappe.qb.DocType("Purchase Invoice Item")
        ITEM = frappe.qb.DocType("Item")

        return (
            frappe.qb.from_(PURCHASE_INVOICE_ITEM)
            .join(ITEM)
            .on(PURCHASE_INVOICE_ITEM.item_code == ITEM.name)
            .select(
                PURCHASE_INVOICE_ITEM.item_code,
                PURCHASE_INVOICE_ITEM.description,
                PURCHASE_INVOICE_ITEM.expense_account,
            )
            .where(PURCHASE_INVOICE_ITEM.parent.isin(invoices))
            .where(ITEM.is_stock_item == 0)
            .run(as_dict=True)
        )

    def get_item(self, item, item_code, **kwargs):
        kwargs["supplier"] = self.doc.supplier

        return frappe.get_doc(
            {
                **super().get_item(item, item_code, **kwargs),
                "doctype": "Purchase Invoice Item",
                "parentfield": "items",
            }
        )

    def set_expense_accounts(self):
        """Set expense accounts for items using AI mapping."""
        items = [row for row in self.doc.items if not row.expense_account]
        if not items:
            return

        expense_accounts = dict(
            frappe.get_all(
                "Account",
                filters={
                    "root_type": "Expense",
                    "is_group": 0,
                    "company": self.doc.company,
                },
                fields=["name", "account_name"],
                as_list=True,
            )
        )

        item_descriptions = [row.description for row in items]

        expense_account_mappings = self.get_expense_account_mapping(
            expense_accounts, item_descriptions
        )

        for row in self.doc.items:
            if not row.expense_account:
                row.expense_account = expense_account_mappings.get(row.description)

    def set_item_tax_template(self):
        if "india_compliance" not in frappe.get_installed_apps():
            return

        # Step 1: Prepare item -> account/rate mapping
        item_conditions_map = self.get_item_conditions_map()
        if not item_conditions_map:
            return

        # Step 2: Build one big OR condition for all accounts across items
        ITT = frappe.qb.DocType("Item Tax Template")
        ITTD = frappe.qb.DocType("Item Tax Template Detail")
        tax_template_conditions = []
        for accounts in item_conditions_map.values():
            for account, rate in accounts.items():
                tax_template_conditions.append(
                    (ITTD.tax_type == account) & (ITTD.tax_rate == rate)
                )

        # Step 3: Query all matching templates in one go
        results = (
            frappe.qb.from_(ITT)
            .join(ITTD)
            .on(ITT.name == ITTD.parent)
            .select(ITT.name, ITTD.tax_type, ITTD.tax_rate)
            .where(ITT.company == self.doc.company)
            .where(Criterion.any(tax_template_conditions))
            .run(as_dict=True)
        )

        # Step 4: Group template rows
        template_map = defaultdict(set)
        for r in results:
            template_map[r.name].add((r.tax_type, r.tax_rate))

        # Step 5: Match templates back to each item
        for idx, accounts in item_conditions_map.items():
            for template, pairs in template_map.items():
                if pairs.issuperset(accounts.items()):
                    self.data.item_list[idx].item_tax_template = template
                    break

    def get_input_tax_accounts(self):
        return frappe.db.get_value(
            "GST Account",
            {"company": self.doc.company, "account_type": "Input"},
            fieldname=["cgst_account", "igst_account", "sgst_account"],
            as_dict=True,
        )

    def get_item_conditions_map(self):
        tax_accounts = self.get_input_tax_accounts()
        if not tax_accounts:
            return {}

        item_conditions_map = {}
        for idx, row in enumerate(self.data.item_list):
            accounts = {}
            for tax in row.taxes:
                account = tax_accounts.get(ACCOUNT_FIELDNAME_MAP.get(tax.description))
                if account:
                    accounts[account] = tax.percentage
            if accounts:
                item_conditions_map[idx] = accounts

        return item_conditions_map

    def get_expense_account_mapping(self, expense_accounts, item_descriptions):
        messages = (
            {
                "role": "system",
                "content": get_expense_account_system_prompt(
                    self.get_expense_account_schema()
                ),
            },
            {
                "role": "user",
                "content": get_expense_account_user_prompt(
                    expense_accounts, item_descriptions
                ),
            },
        )

        ai_parser = AIParser(self.ai_model)
        response_data = ai_parser.get_content(ai_parser.send_message(messages=messages))

        return {row.item_description: row.expense_account for row in response_data}
