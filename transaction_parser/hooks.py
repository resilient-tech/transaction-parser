app_name = "transaction_parser"
app_title = "Transaction Parser"
app_publisher = "Resilient Tech"
app_description = "AI-powered add-on for ERPNext that extracts data from PDFs, CSV, and Excel files and creates draft records automatically."
app_email = "info@resilient.tech"
app_license = "GNU General Public License (v3)"
required_apps = ["frappe/erpnext"]

after_install = "transaction_parser.install.after_install"
before_uninstall = "transaction_parser.uninstall.before_uninstall"

after_app_install = "transaction_parser.install.after_app_install"
before_app_uninstall = "transaction_parser.uninstall.before_app_uninstall"

before_tests = "transaction_parser.tests.before_tests"

app_include_js = "transaction_parser.bundle.js"

extend_bootinfo = "transaction_parser.boot.boot_session"

doctype_js = {
    "Sales Order": "public/js/sales_order.js",
    "Communication": "public/js/communication.js",
}

doctype_list_js = {
    "Sales Order": "transaction_parser/client_scripts/sales_order_list.js",
    "Purchase Invoice": "transaction_parser/client_scripts/purchase_invoice_list.js",
}

doc_events = {
    "Communication": {
        "on_update": "transaction_parser.transaction_parser.overrides.communication.on_update",
    }
}

export_python_type_annotations = True

scheduler_events = {
    "cron": {
        # at 2:00 am every day
        "0 2 * * *": [
            "transaction_parser.parser_benchmark.doctype.parser_benchmark_settings.parser_benchmark_settings.run_scheduled_benchmarks",
        ],
    }
}
