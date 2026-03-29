$(document).on('form-refresh', function () {
	setTimeout(function () {
		if (!cur_frm || !cur_frm.fields_dict.accounting_dimensions_section) return;

		var section = cur_frm.fields_dict.accounting_dimensions_section;
		// expand section so fields are visible
		if (section.collapse) {
			section.collapse(false);
		}
		// remove collapsible
		cur_frm.set_df_property('accounting_dimensions_section', 'collapsible', 0);
		// hide the section head label and arrow
		if (section.$wrapper) {
			section.$wrapper.find('.section-head, .collapse-indicator').hide();
		}
		if (section.head) {
			$(section.head).hide();
		}
	}, 500);
});
