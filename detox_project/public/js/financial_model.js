// Financial Model (Project Budget): hide the Loan Terms and Means of Finance
// sections (CR-02 / CR-03) and the whole RESULT tab (CR-05).

frappe.ui.form.on("Financial Model", {
	onload(frm) {
		fm_hide_sections(frm);
	},
	refresh(frm) {
		fm_hide_sections(frm);
	},
});

function fm_hide_sections(frm) {
	const hidden_fields = [
		// CR-02: Loan Terms (CAPEX tab) and the OPEX-side loan-term fields
		"sec_loan_terms",
		"loan_tenure_years",
		"interest_rate_tl",
		"interest_rate_reduction",
		"moratorium_years",
		"working_capital_amount",
		"interest_rate_wc",
		"interest_on_wc_annual",
		"custom_opex_working_capital",
		"custom_opex_interest_rate_wc",
		"custom_opex_interest_on_wc_annual",
		"custom_opex_moratorium_years",
		// CR-03: Means of Finance (CAPEX tab)
		"sec_means_of_finance",
		"equity_amount",
		"equity_percent",
		"loan_amount",
		"loan_percent",
		// CR-05: RESULT tab
		"custom_result",
		"ebitda",
		"ebitda_percent",
		"gross_profit",
		"gross_profit_percent",
		"depreciation_annual",
		"interest_annual",
		"ebit",
		"pbt",
		"tax_rate",
		"pat",
		"pat_percent",
		"project_irr",
		"equity_irr",
		"npv",
		"discount_rate",
		"terminal_growth_rate",
		"payback_period_years",
		"avg_dscr",
		"min_dscr",
		"terminal_value",
		"wbs_status",
		"sub_wbs_status",
	];
	hidden_fields.forEach((fieldname) => frm.set_df_property(fieldname, "hidden", 1));

	// The tab label stays visible after hiding the Tab Break; hide it and leave the tab if it is open.
	setTimeout(() => {
		$("#financial-model-custom_result-tab").closest("li").hide();
		const active_tab_id = $(".form-tabs li.active a").attr("id") || "";
		if (active_tab_id.includes("custom_result")) {
			$(".form-tabs li:visible:first a").click();
		}
	}, 100);
}
