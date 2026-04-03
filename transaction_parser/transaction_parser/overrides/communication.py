import frappe

from transaction_parser.transaction_parser import _parse

PARTY_TYPE_MAP = {"Sales Order": "Customer", "Expense": "Supplier"}


def on_update(doc, method=None):
    if doc.communication_type != "Communication" or doc.sent_or_received != "Received":
        return

    settings = frappe.get_cached_doc("Transaction Parser Settings")
    if not (settings.enabled and settings.parse_incoming_emails):
        return

    if settings.parse_party_emails:
        matched_party_config = next(
            (row for row in settings.party_emails if row.party_email == doc.sender),
            None,
        )

        if matched_party_config:
            if matched_party_config.party_type == "Supplier":
                transaction_type = "Expense"
            else:
                transaction_type = "Sales Order"

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
            )
            return

    matched_account = next(
        (
            row
            for row in settings.incoming_email_accounts
            if row.to_email in doc.recipients
        ),
        None,
    )

    if not matched_account:
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
    matched_party = next(
        (
            row.party
            for row in settings.party_emails
            if row.party_type == party_type and row.party_email == doc.sender
        ),
        None,
    )

    _process_attachments(
        doc,
        attachments,
        matched_account.transaction,
        settings,
        matched_account.user,
        matched_party,
        matched_account.company,
    )


def _process_attachments(
    doc, attachments, transaction_type, settings, user, party, company=None
):
    if not company:
        default_company = frappe.defaults.get_user_default("Company")
        country = frappe.db.get_value("Company", default_company, "country")
        country = "India" if country == "India" else "Other"
    else:
        country = frappe.db.get_value("Company", company, "country")

    supported_extensions = {"pdf", "xlsx", "xls", "csv"}
    filtered_attachments = [
        attachment
        for attachment in attachments
        if attachment.file_url.split(".")[-1].lower() in supported_extensions
    ]

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
        now=True,
    )


def _parse_attachments(
    doc, country, transaction_type, attachments, ai_model, user, party, company
):
    settings = frappe.get_cached_doc("Transaction Parser Settings")

    if settings.process_one_document_per_communication:
        file_urls = [attachment.file_url for attachment in attachments]
        _parse(
            country=country,
            transaction=transaction_type,
            file_urls=file_urls,
            ai_model=ai_model,
            user=user,
            party=party,
            company=company,
            communication_name=doc.name,
        )
        frappe.db.commit()
    else:
        for attachment in attachments:
            _parse(
                country=country,
                transaction=transaction_type,
                file_urls=attachment.file_url,
                ai_model=ai_model,
                user=user,
                party=party,
                company=company,
            )
            frappe.db.commit()

    doc.db_set("is_processed_by_transaction_parser", 1)
