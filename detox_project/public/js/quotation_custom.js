frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new()) {
			reset_naming_series(frm);
		}
	},
});

function reset_naming_series(frm) {
	let naming_field = frm.fields_dict.naming_series;
	if (!naming_field) return;

	let options = (naming_field.df.options || "").split("\n").filter(Boolean);
	if (options.length && !options.includes(frm.doc.naming_series)) {
		frm.set_value("naming_series", options[0]);
	}
}
