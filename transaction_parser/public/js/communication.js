const SUPPORTED_EXTENSIONS = ["pdf", "xlsx", "xls", "csv"];

const PARTY_TYPE_MAP = {
	"Sales Order": "Customer",
	Expense: "Supplier",
};

frappe.ui.form.on("Communication", {
	refresh(frm) {
		if (frm.is_new() || !frappe.boot.transaction_parser_enabled) return;
		if (!has_supported_attachments(frm)) return;

		frm.add_custom_button(__("Parse"), () => show_parse_dialog(frm));
	},
});

function has_supported_attachments(frm) {
	const attachments = frm.get_docinfo()?.attachments || [];
	return attachments.some((attachment) =>
		SUPPORTED_EXTENSIONS.includes((attachment.file_url || "").split(".").pop().toLowerCase())
	);
}

async function show_parse_dialog(frm) {
	const { message: defaults } = await frappe.call({
		method: "transaction_parser.transaction_parser.overrides.communication.get_parse_defaults",
		args: { communication: frm.doc.name },
		freeze: true,
	});

	const party_type = PARTY_TYPE_MAP[defaults.transaction];

	const dialog = new frappe.ui.Dialog({
		title: __("Parse Communication"),
		fields: [
			{
				fieldname: "transaction",
				label: __("Transaction"),
				fieldtype: "Select",
				options: [
					{ value: "Sales Order", label: __("Sales Order") },
					{ value: "Expense", label: __("Expense Invoice") },
				],
				default: defaults.transaction,
				reqd: 1,
				onchange() {
					const party_type = PARTY_TYPE_MAP[this.get_value()];
					dialog.set_df_property("party", "options", party_type);
					dialog.set_df_property("party", "label", __(party_type || "Party"));
					dialog.set_value("party", defaults.parties[party_type] || "");
				},
			},
			{
				fieldname: "company",
				label: __("Company"),
				fieldtype: "Link",
				options: "Company",
				default: defaults.company,
				reqd: 1,
			},
			{
				fieldname: "party",
				label: __(party_type || "Party"),
				fieldtype: "Link",
				options: party_type,
				default: defaults.parties[party_type],
				description: __("Leave empty to let the parser identify the party"),
			},
			{
				fieldtype: "Column Break",
			},
			{
				fieldname: "ai_model",
				label: __("AI Model"),
				fieldtype: "Select",
				options: defaults.supported_models,
				default: defaults.ai_model,
				reqd: 1,
			},
			{
				fieldname: "page_limit",
				label: __("Page Limit"),
				fieldtype: "Int",
			},
			{
				fieldname: "process_one_document",
				label: __("Combine all attachments into one document"),
				fieldtype: "Check",
				default: defaults.process_one_document,
			},
			{
				fieldtype: "Section Break",
			},
			{
				fieldname: "attachments",
				label: __("Attachments"),
				fieldtype: "MultiCheck",
				columns: 1,
				options: defaults.attachments.map((attachment) => ({
					label: attachment.file_name || attachment.file_url,
					value: attachment.file_url,
					checked: 1,
				})),
			},
		],
		primary_action_label: __("Parse"),
		primary_action(values) {
			if (!values.attachments?.length) {
				frappe.throw(__("Please select at least one attachment to parse"));
			}

			const parse = () =>
				frappe.call({
					method: "transaction_parser.transaction_parser.overrides.communication.parse_communication",
					args: {
						communication: frm.doc.name,
						...values,
					},
					freeze: true,
					callback() {
						frappe.show_alert({ message: __("Parsing started"), indicator: "green" });
						dialog.hide();
						frm.reload_doc();
					},
				});

			if (defaults.is_processed) {
				frappe.confirm(__("This communication has already been parsed. Parse again?"), parse);
			} else {
				parse();
			}
		},
	});

	dialog.show();
}
