import frappe
from frappe import _
from frappe.utils import cint

from transaction_parser.transaction_parser import TRANSACTION_MAP, _parse
from transaction_parser.transaction_parser.doctype.transaction_parser_settings.transaction_parser_settings import (
    get_ai_models,
)
from transaction_parser.transaction_parser.utils import is_enabled

PARTY_TYPE_MAP = {"Sales Order": "Customer", "Expense": "Supplier"}
SUPPORTED_EXTENSIONS = {"pdf", "xlsx", "xls", "csv"}


def on_update(doc, method=None):
    if doc.communication_type != "Communication" or doc.sent_or_received != "Received":
        return

    settings = frappe.get_cached_doc("Transaction Parser Settings")
    if not (settings.enabled and settings.parse_incoming_emails):
        return

    matched_account = _get_matched_account(settings, doc)
    if not matched_account:
        return

    if settings.parse_party_emails:
        matched_party_config = _get_matched_party(settings, doc.sender)

        if matched_party_config:
            transaction_type = _get_transaction_for_party_type(
                matched_party_config.party_type
            )
            default_user = frappe.session.user

            # Attachments are not available when the Communication doc is created.
            # Next time the doc is updated, we will check for attachments,
            # and update the flag `is_processed_by_transaction_parser` accordingly.
            attachments = doc.get_attachments()
            if not attachments:
                return

            _process_attachments(
                doc,
                attachments,
                transaction_type,
                settings,
                default_user,
                matched_party_config.party,
                matched_account.company,
            )
            return

    # Attachments are not available when the Communication doc is created.
    # Next time the doc is updated, we will check for attachments,
    # and update the flag `is_processed_by_transaction_parser` accordingly.
    attachments = doc.get_attachments()
    if not attachments:
        return

    process_attachments(doc, settings, matched_account, attachments)


def process_attachments(doc, settings, matched_account, attachments):
    party_type = PARTY_TYPE_MAP[matched_account.transaction]
    matched_party = _get_matched_party(settings, doc.sender, party_type)

    _process_attachments(
        doc,
        attachments,
        matched_account.transaction,
        settings,
        matched_account.user,
        matched_party.party if matched_party else None,
        matched_account.company,
    )


def _process_attachments(
    doc, attachments, transaction_type, settings, user, party, company=None
):
    if not company:
        default_company = frappe.defaults.get_user_default("Company")
        country = _get_country(default_company)
    else:
        country = frappe.db.get_value("Company", company, "country")

    filtered_attachments = _filter_supported_attachments(attachments)
    if not filtered_attachments:
        return

    frappe.enqueue(
        "transaction_parser.transaction_parser.overrides.communication._parse_attachments",
        doc=doc,
        country=country,
        transaction_type=transaction_type,
        attachments=filtered_attachments,
        ai_model=settings.default_ai_model,
        user=user,
        party=party,
        company=default_company if not company else company,
        queue="long",
    )


def _parse_attachments(
    doc,
    country,
    transaction_type,
    attachments,
    ai_model,
    user,
    party,
    company,
    process_one_document=None,
    page_limit=None,
):
    if process_one_document is None:
        settings = frappe.get_cached_doc("Transaction Parser Settings")
        process_one_document = settings.process_one_document_per_communication

    if process_one_document:
        file_urls = [attachment.file_url for attachment in attachments]
        _parse(
            country=country,
            transaction=transaction_type,
            file_urls=file_urls,
            ai_model=ai_model,
            page_limit=page_limit,
            user=user,
            party=party,
            company=company,
        )
        frappe.db.commit()
    else:
        for attachment in attachments:
            _parse(
                country=country,
                transaction=transaction_type,
                file_urls=attachment.file_url,
                ai_model=ai_model,
                page_limit=page_limit,
                user=user,
                party=party,
                company=company,
            )
            frappe.db.commit()

    # keep `modified` unchanged so an open form can still be saved
    doc.db_set("is_processed_by_transaction_parser", 1, update_modified=False)


@frappe.whitelist()
def get_parse_defaults(communication):
    settings = frappe.get_cached_doc("Transaction Parser Settings")
    is_enabled(settings)

    doc = frappe.get_doc("Communication", communication)
    doc.check_permission("read")

    matched_account = _get_matched_account(settings, doc)

    transaction = matched_account.transaction if matched_account else None
    if settings.parse_party_emails:
        matched_party_config = _get_matched_party(settings, doc.sender)
        if matched_party_config:
            transaction = _get_transaction_for_party_type(
                matched_party_config.party_type
            )

    parties = {}
    for party_type in PARTY_TYPE_MAP.values():
        matched_party = _get_matched_party(settings, doc.sender, party_type)
        parties[party_type] = matched_party.party if matched_party else None

    ai_models = get_ai_models()

    return {
        "transaction": transaction,
        "company": (matched_account.company if matched_account else None)
        or frappe.defaults.get_user_default("Company"),
        "parties": parties,
        "ai_model": ai_models["default_model"],
        "supported_models": ai_models["supported_models"],
        "process_one_document": cint(settings.process_one_document_per_communication),
        "attachments": [
            {"file_url": attachment.file_url, "file_name": attachment.file_name}
            for attachment in _get_supported_attachments(doc)
        ],
        "is_processed": cint(doc.get("is_processed_by_transaction_parser")),
    }


@frappe.whitelist()
def parse_communication(
    communication,
    transaction,
    company,
    attachments,
    party=None,
    ai_model=None,
    page_limit=None,
    process_one_document=0,
):
    is_enabled()

    if transaction not in TRANSACTION_MAP:
        frappe.throw(_("Invalid transaction type: {0}").format(transaction))

    doc = frappe.get_doc("Communication", communication)
    doc.check_permission("read")

    frappe.has_permission(TRANSACTION_MAP[transaction], "create", throw=True)
    if not frappe.db.exists("Company", company):
        frappe.throw(_("Company {0} does not exist").format(company))

    frappe.has_permission("Company", "read", company, throw=True)

    party_type = PARTY_TYPE_MAP[transaction]
    if party and not frappe.db.exists(party_type, party):
        frappe.throw(_("{0} {1} does not exist").format(_(party_type), party))

    supported_models = get_ai_models()["supported_models"].split("\n")
    if ai_model and ai_model not in supported_models:
        frappe.throw(_("Unsupported AI Model: {0}").format(ai_model))

    file_urls = frappe.parse_json(attachments) or []
    if isinstance(file_urls, str):
        file_urls = [file_urls]

    if not file_urls:
        frappe.throw(_("Please select at least one attachment to parse"))

    supported_attachments = {
        attachment.file_url: attachment
        for attachment in _get_supported_attachments(doc)
    }
    invalid_file_urls = [url for url in file_urls if url not in supported_attachments]
    if invalid_file_urls:
        frappe.throw(
            _("The following files are not supported attachments of {0}: {1}").format(
                communication, ", ".join(invalid_file_urls)
            )
        )

    # mark now, so parsing again before the job finishes asks for confirmation
    doc.db_set("is_processed_by_transaction_parser", 1, update_modified=False)

    frappe.enqueue(
        "transaction_parser.transaction_parser.overrides.communication._parse_attachments",
        doc=doc,
        country=_get_country(company),
        transaction_type=transaction,
        attachments=[supported_attachments[url] for url in file_urls],
        ai_model=ai_model or None,
        user=frappe.session.user,
        party=party or None,
        company=company,
        process_one_document=cint(process_one_document),
        page_limit=cint(page_limit) or None,
        queue="long",
        now=frappe.conf.developer_mode,
    )


def _get_matched_account(settings, doc):
    return next(
        (
            row
            for row in settings.incoming_email_accounts
            if row.to_email in (doc.recipients or "")
        ),
        None,
    )


def _get_matched_party(settings, sender, party_type=None):
    return next(
        (
            row
            for row in settings.party_emails
            if row.party_email == sender
            and (not party_type or row.party_type == party_type)
        ),
        None,
    )


def _get_transaction_for_party_type(party_type):
    return "Expense" if party_type == "Supplier" else "Sales Order"


def _get_supported_attachments(doc):
    return _filter_supported_attachments(doc.get_attachments())


def _filter_supported_attachments(attachments):
    return [
        attachment
        for attachment in attachments
        if attachment.file_url.split(".")[-1].lower() in SUPPORTED_EXTENSIONS
    ]


def _get_country(company):
    country = frappe.db.get_value("Company", company, "country")
    return "India" if country == "India" else "Other"
