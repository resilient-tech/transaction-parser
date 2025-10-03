import json

import frappe
from frappe import _

from transaction_parser.transaction_parser.utils import pretty_json
from transaction_parser.utils import execute_in_new_transaction

SERVICE_NAME = "Transaction Parser API"


@execute_in_new_transaction
def create_integration_request(
    url=None,
    request_id=None,
    request_headers=None,
    data=None,
    output=None,
    error=None,
    reference_doctype=None,
    reference_name=None,
):
    return frappe.get_doc(
        {
            "doctype": "Integration Request",
            "integration_request_service": SERVICE_NAME,
            "request_id": request_id,
            "url": url,
            "request_headers": pretty_json(request_headers),
            "data": pretty_json(data),
            "output": pretty_json(output),
            "error": pretty_json(error),
            "status": "Failed" if error else "Completed",
            "reference_doctype": reference_doctype,
            "reference_docname": reference_name,
        }
    ).insert(ignore_permissions=True)
