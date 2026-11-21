import frappe

from transaction_parser.transaction_parser import TRANSACTION_MAP
from transaction_parser.transaction_parser.overrides.communication import (
    PARTY_TYPE_MAP,
    SUPPORTED_EXTENSIONS,
)
from transaction_parser.transaction_parser.utils import is_enabled


def boot_session(bootinfo):
    bootinfo.transaction_parser = {
        "enabled": is_enabled(throw=False),
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "party_types": PARTY_TYPE_MAP,
        # transactions the user can create, offered in the Communication Parse dialog
        "transactions": [
            transaction
            for transaction, doctype in TRANSACTION_MAP.items()
            if frappe.has_permission(doctype, "create")
        ],
    }
