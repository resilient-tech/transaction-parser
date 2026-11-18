import json
from unittest import TestCase

from transaction_parser.transaction_parser.utils import to_dict
from transaction_parser.transaction_parser.utils.response_merger import ResponseMerger

PARTY_SCHEMA = {
    "name": "string",
    "address": {"city": "string"},
    "contact": {"email": ["string"], "phone": ["string"]},
}

SCHEMA = {
    "document_number": "string",
    "buyer": {"billing": PARTY_SCHEMA, "shipping": PARTY_SCHEMA},
}


def as_response(data: dict):
    return to_dict(json.dumps(data))


def merge(first: dict, second: dict):
    merger = ResponseMerger(as_response(first), schema=SCHEMA)
    merger.merge(as_response(second))
    return merger.response


SECOND = {
    "document_number": "1991347259",
    "buyer": {
        "billing": {
            "name": "Brack AG",
            "contact": {"email": ["billing@example.com"], "phone": []},
        },
        "shipping": {
            "name": "Brack AG",
            "address": {"city": "Willisau"},
            "contact": {"email": [], "phone": []},
        },
    },
}

BILLING_ONLY = {
    "name": "Brack AG",
    "contact": {"email": ["billing@example.com"], "phone": ["062 889 62 68"]},
}


class TestResponseMerger(TestCase):
    def test_empty_lists_kept_when_object_was_null(self):
        data = merge({"buyer": {"billing": BILLING_ONLY, "shipping": None}}, SECOND)

        self.assertEqual(data.buyer.shipping.contact.email, [])
        self.assertEqual(data.buyer.shipping.contact.phone, [])
        self.assertEqual(data.buyer.shipping.address.city, "Willisau")

    def test_empty_lists_kept_when_contact_was_null(self):
        first = {
            "buyer": {
                "billing": BILLING_ONLY,
                "shipping": {"name": "Brack AG", "contact": None},
            }
        }
        data = merge(first, SECOND)

        self.assertEqual(data.buyer.shipping.contact.email, [])
        self.assertEqual(data.buyer.shipping.contact.phone, [])

    def test_empty_list_replaces_null_list(self):
        first = {
            "buyer": {
                "billing": BILLING_ONLY,
                "shipping": {
                    "name": "Brack AG",
                    "contact": {"email": None, "phone": None},
                },
            }
        }
        data = merge(first, SECOND)

        self.assertEqual(data.buyer.shipping.contact.email, [])

    def test_existing_values_not_overwritten(self):
        data = merge(
            {"document_number": "PO-1", "buyer": {"billing": BILLING_ONLY}}, SECOND
        )

        self.assertEqual(data.document_number, "PO-1")
        self.assertEqual(data.buyer.billing.contact.email, ["billing@example.com"])
        self.assertEqual(data.buyer.billing.contact.phone, ["062 889 62 68"])

    def test_null_source_does_not_create_keys(self):
        data = merge(
            {"buyer": {"billing": BILLING_ONLY}}, {"buyer": {"shipping": None}}
        )

        self.assertIsNone(data.buyer.get("shipping"))

    def test_non_empty_list_fills_empty_list(self):
        first = {
            "buyer": {
                "billing": {"name": "Brack AG", "contact": {"email": [], "phone": []}}
            }
        }
        data = merge(first, SECOND)

        self.assertEqual(data.buyer.billing.contact.email, ["billing@example.com"])
