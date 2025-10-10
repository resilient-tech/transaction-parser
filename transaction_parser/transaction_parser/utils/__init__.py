import json
from functools import wraps

import frappe
from frappe import _


def is_enabled(settings=None, throw=True):
    if not settings:
        settings = frappe.get_cached_doc("Transaction Parser Settings")

    if not settings.enabled and throw:
        frappe.throw(_("Please enable Transaction Parser Settings"))

    return settings.enabled


def pretty_json(obj):
    if not obj:
        return ""

    if isinstance(obj, str):
        return obj

    return frappe.as_json(obj, indent=4)


def to_dict(value, throw=True):
    try:
        return json.loads(value, object_hook=frappe._dict)

    except Exception:
        if throw:
            frappe.throw(_("Invalid JSON"))

        return frappe._dict()


def execute_in_new_transaction(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        _db = frappe.local.db
        try:
            frappe.connect(set_admin_as_user=False)
            result = fn(*args, **kwargs)
            frappe.db.commit()  # nosemgrep
            return result

        finally:
            frappe.db.close()
            frappe.local.db = _db

    return wrapper
