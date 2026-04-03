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
    )


def _parse(
    country,
    transaction,
    file_urls,
    ai_model=None,
    page_limit=None,
    user=None,
    party=None,
    company=None,
    communication_name=None,
):
    try:
        if (
            isinstance(file_urls, str)
            and file_urls.startswith("[")
            and file_urls.endswith("]")
        ):
            file_urls = frappe.parse_json(file_urls)

        elif isinstance(file_urls, str):
            file_urls = [file_urls]

        file_names = frappe.get_list(
            "File",
            filters={"file_url": ("in", file_urls)},
            fields=["name", "file_type"],
            order_by="creation desc",
            group_by="file_url",
        )

        # xlsx/xls first, then pdf, then csv. If no xlsx/xls, csv takes its place.
        file_types = {(f.file_type or "").lower() for f in file_names}
        has_spreadsheet = file_types & {"xlsx", "xls"}

        if has_spreadsheet:
            FILE_TYPE_PRIORITY = {"xlsx": 0, "xls": 0, "pdf": 1, "csv": 2}
        else:
            FILE_TYPE_PRIORITY = {"csv": 0, "pdf": 1}

        file_names.sort(
            key=lambda f: FILE_TYPE_PRIORITY.get((f.file_type or "").lower(), 99)
        )

        files = []
        for file_name in file_names:
            file = frappe.get_doc("File", file_name)
            files.append(file)

        controller = get_controller(country, transaction)(party=party, company=company)
        doc = controller.generate(files, ai_model, page_limit)

        filenames = (
            ", ".join([f.file_name for f in files])
            if len(files) > 1
            else files[0].file_name
        )
        notification = {
            "document_type": TRANSACTION_MAP[transaction],
            "document_name": doc.name,
            "subject": _("{0} {1} generated from {2}").format(
                _(TRANSACTION_MAP[transaction]),
                doc.name,
                filenames,
            ),
        }

    except Exception as e:
        notification = None
        reference_doctype = "Communication" if communication_name else "File"
        reference_docname = (
            communication_name
            if communication_name
            else (files[0].name if files else None)
        )

        if (
            isinstance(e, frappe.DuplicateEntryError)
            and frappe.flags.skip_duplicate_error
        ):
            subject = _("Duplicate {0} found for {1}").format(
                _(TRANSACTION_MAP[transaction]),
                f"{reference_doctype} {reference_docname}",
            )

            notification = {
                "document_type": reference_doctype,
                "document_name": reference_docname,
                "subject": subject,
                "message": str(e),
            }

        if not (error_log := getattr(e, "error_log", None)):
            error_log = frappe.log_error(
                "Transaction Parser Error",
                reference_doctype=reference_doctype,
                reference_name=reference_docname,
            )

        message = _("Failed to generate {0} from {1}").format(
            TRANSACTION_MAP[transaction], f"{reference_doctype} {reference_docname}"
        )

        notification = {
            "document_type": error_log.doctype,
            "document_name": error_log.name,
            "subject": message,
            "message": str(e),
        }

        email_failure(user, message, str(e), file_urls)

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
