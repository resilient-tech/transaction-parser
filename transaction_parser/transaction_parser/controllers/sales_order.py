import frappe
import frappe.utils
from frappe import _

from transaction_parser.transaction_parser.controllers.transaction import Transaction


class SalesOrder(Transaction):
    DOCTYPE = "Sales Order"
    PARTY_DOCTYPE = "Customer"

    ###################################
    ########## Output Schema ##########
    ###################################

    def get_default_schema(self):
        return {
            **super().get_default_schema(),
            "purchase_order_date": "date | null (Also called `Order Date`. It can be different than Document Date)",
            "delivery_date": "date | null",
            "project_reference": "string | null",
            "buyer": {
                "shipping": self.get_party_schema(),
                "billing": self.get_party_schema(),
            },
            "vendor": self.get_party_schema(),
        }

    ##################################
    ########## Data Mapping ##########
    ##################################

    def set_details(self):
        self.doc.company = self.get_company()
        if not self.doc.company:
            frappe.throw("Company not found")

        self.doc.customer = self.get_customer()
        # if not self.doc.customer:
        #     self.create_party()

        self.doc.po_no = self.data.document_number
        self.validate_po_no()

        self.doc.po_date = self.data.purchase_order_date
        self.doc.delivery_date = self.data.delivery_date
        self.doc.currency = self.data.currency or None

        today = frappe.utils.today()
        self.doc.transaction_date = (
            delivery_date
            if (delivery_date := self.doc.delivery_date) and (delivery_date < today)
            else today
        )

        self.set_exchange_rate(
            self.doc.currency, self.doc.transaction_date, "for_selling"
        )

        self.doc.company_address = self.get_company_address()
        self.doc.customer_address = self.get_billing_address()
        self.doc.shipping_address_name = self.get_shipping_address()

        self.doc.contact_person = self.get_party_contact(
            self.data.buyer.billing, self.data.buyer.shipping
        )

        self.doc.ignore_pricing_rule = 1

        self.doc.items = self.get_items()
        # self.doc.payment_schedule = self.get_payment_schedule()
        self.doc.terms = self.get_terms()
        # TODO: validation of Sales Order on save.

    def validate_po_no(self):
        if so_name := frappe.db.exists(
            "Sales Order", {"po_no": self.doc.po_no, "docstatus": 1}
        ):
            frappe.throw(
                _(
                    f"Duplicate Sales Order {so_name} found with PO number {self.doc.po_no}"
                ),
                frappe.DuplicateEntryError,
            )

    def set_missing_values(self):
        self.doc.set_missing_values()
        self.doc.calculate_taxes_and_totals()

    ### Company

    def get_company(self):
        self.company_found_against = None
        if self.company:
            return self.company

        party_type = "Company"
        fieldname = "name"

        company_identification_order = (
            ("vendor", self.data.vendor),
            ("buyer", self.data.buyer.billing),
            ("buyer", self.data.buyer.shipping),
        )

        # search
        for key, party in company_identification_order:
            if found := self.search_party(party, party_type, fieldname):
                self.company_found_against = key
                return found

        # guess
        party_names = frappe.get_all(party_type, pluck="name")
        for key, party in company_identification_order:
            if found := self.guess_party(party, party_type, party_names):
                self.company_found_against = key
                return found

    ### Customer

    def get_customer(self):
        if self.party:
            return self.party

        party_type = "Customer"
        fieldname = "customer_name"
        # search

        customer_identification_order = (
            ("buyer", self.data.buyer.billing),
            ("buyer", self.data.buyer.shipping),
            ("vendor", self.data.vendor),
        )

        # search
        for key, party in customer_identification_order:
            if key == self.company_found_against:
                continue

            if found := self.search_party(party, party_type, fieldname):
                return found

        # guess
        party_names = dict(
            frappe.get_all(party_type, fields=["name", "customer_name"], as_list=True)
        )
        for key, party in customer_identification_order:
            if key == self.company_found_against:
                continue

            if found := self.guess_party(party, party_type, party_names):
                return found

    # def create_party(self):
    #     # TODO: Implement
    #     # as a part of settings / only for india
    #     # from india_compliance API
    #     pass

    ### Address

    def get_company_address(self):
        if found := self.get_address(
            frappe._dict({**self.data.vendor, "name": self.doc.company}),
            "Company",
            self.data.vendor.address,
        ):
            return found

    def get_billing_address(self):
        if found := self.get_address(
            frappe._dict({**self.data.buyer.billing, "name": self.doc.customer}),
            "Customer",
            self.data.buyer.billing.address,
        ):
            return found

    def get_shipping_address(self):
        if found := self.get_address(
            frappe._dict({**self.data.buyer.shipping, "name": self.doc.customer}),
            "Customer",
            self.data.buyer.shipping.address,
        ):
            return found

    ### Items

    def get_items(self):
        if not self.data.item_list:
            return []

        customer_item_codes = [item.party_item_code for item in self.data.item_list]

        filters = {
            "parenttype": "Item",
            "customer_name": self.doc.customer,
            "ref_code": ["in", customer_item_codes],
        }

        item_codes = frappe._dict(
            frappe.get_all(
                "Item Customer Detail",
                filters=filters,
                fields=["ref_code", "parent"],
                as_list=True,
            )
        )

        price_list = frappe.db.get_value(
            "Customer", {"name": self.doc.customer}, "default_price_list"
        )

        if not price_list:
            price_list = frappe.db.get_single_value(
                "Selling Settings", "selling_price_list"
            )

        items = [
            self.get_item(
                item,
                item_codes.get(item.party_item_code),
                price_list=price_list,
                ignore_pricing_rule=self.doc.ignore_pricing_rule,
                transaction_date=self.doc.transaction_date,
                conversion_rate=self.doc.conversion_rate,
            )
            for item in self.data.item_list
        ]

        for idx, item in enumerate(items):
            item.idx = idx + 1

        return items

    def get_item(self, item, item_code, **kwargs):
        kwargs["customer"] = self.doc.customer

        return frappe.get_doc(
            {
                **super().get_item(item, item_code, **kwargs),
                "doctype": "Sales Order Item",
                "parentfield": "items",
                "customer_item_code": item.party_item_code,
            }
        )
