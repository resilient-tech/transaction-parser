import frappe
from frappe import _
from frappe.utils import cint, cstr

from transaction_parser.transaction_parser.controllers import get_controller
from transaction_parser.transaction_parser.utils import is_enabled
from transaction_parser.transaction_parser.utils.notification import (
    enqueue_notification,
)

TRANSACTION_MAP = {
    "Sales Order": "Sales Order",
    "Expense": "Purchase Invoice",
}


@frappe.whitelist()
def parse(transaction, country, file_url, ai_model=None, page_limit=None):
    is_enabled()

    frappe.has_permission(TRANSACTION_MAP[transaction], "create", throw=True)

    frappe.enqueue(
        _parse,
        country=cstr(country),
        transaction=cstr(transaction),
        file_url=cstr(file_url),
        ai_model=cstr(ai_model),
        page_limit=cint(page_limit),
        queue="long",
        now=frappe.conf.developer_mode,
    )


def _parse(
    country,
    transaction,
    file_url,
    ai_model=None,
    page_limit=None,
    user=None,
    party=None,
    company=None,
):
    try:
        file = None
        filename = file_url.split("/")[-1]

        file = frappe.get_last_doc("File", filters={"file_url": file_url})
        filename = file.file_name

        controller = get_controller(country, transaction)(party=party, company=company)
        doc = controller.generate(file, ai_model, page_limit)

        notification = {
            "document_type": TRANSACTION_MAP[transaction],
            "document_name": doc.name,
            "subject": _("{0} {1} generated from {2}").format(
                _(TRANSACTION_MAP[transaction]),
                doc.name,
                filename,
            ),
        }

    except Exception as e:
        notification = None

        if (
            isinstance(e, frappe.DuplicateEntryError)
            and frappe.flags.skip_duplicate_error
        ):
            notification = {
                "document_type": "File",
                "document_name": file.name if file else filename,
                "subject": _("Duplicate entry found for {0}").format(filename),
                "message": str(e),
            }
            return

        error_log = frappe.log_error(
            "Transaction Parser API Error",
            reference_doctype="File",
            reference_name=file.name if file else filename,
        )
        message = _("Failed to generate {0} from {1}").format(_(transaction), filename)

        notification = {
            "document_type": error_log.doctype,
            "document_name": error_log.name,
            "subject": message,
            "message": str(e),
        }

        email_failure(user, message, str(e), file_url)

    finally:
        if notification:
            enqueue_notification(**notification)


def email_failure(user, subject, error_message, file_url):
    recipient = frappe.db.get_value("User", user, "email")

    frappe.sendmail(
        recipients=recipient,
        subject=subject,
        message=_(
            "Hello,<br><br>We were unable to process your email attachment for transaction parsing.<br><br>Error: {0}<br><br>Please check the attachment and process it manually if required."
        ).format(error_message),
        attachments=[{"file_url": file_url}],
    )
