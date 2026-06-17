// ABP2-I419 Phase 1 (Sahil 2026-06-15, Out of BRD) — Production Plan
// client logic for the No-BOM mode (FR-01..06, Process Logic L01..L04).
//
// L01 — When custom_no_bom is checked, hide the standard BOM / Sales
//       Order / Material Request sections and show the custom FG +
//       Operations tables.
// L02 — Recompute Table 1 row.total_standard_cost on qty / rate change.
// L03 — Recompute Table 2 row.multiply_by = qty_per_unit * SUM(Table 1
//       qty_to_manufacture) on Table 1 qty change, form_render, refresh.
// L04 — When a Table 1 item_code is set, pre-fill standard_costing_rate
//       from Item.valuation_rate; user may override.

frappe.ui.form.on("Production Plan", {
    onload(frm) {
        _apply_no_bom_visibility(frm);
    },

    refresh(frm) {
        _apply_no_bom_visibility(frm);
        _recompute_multiply_by(frm);
    },

    custom_no_bom(frm) {
        _apply_no_bom_visibility(frm);
    },
});

frappe.ui.form.on("Detox Production Plan FG", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;
        // L04 — pre-fill standard_costing_rate from Item.valuation_rate
        // (only when blank, so a manual override isn't clobbered on a
        // subsequent item_code re-select).
        if (row.standard_costing_rate) return;
        frappe.db.get_value("Item", row.item_code, "valuation_rate")
            .then(r => {
                const v = r && r.message && r.message.valuation_rate;
                if (v) {
                    frappe.model.set_value(cdt, cdn, "standard_costing_rate", v);
                }
            });
    },

    qty_to_manufacture(frm, cdt, cdn) {
        _recompute_total_standard_cost(cdt, cdn);
        _recompute_multiply_by(frm);
    },

    standard_costing_rate(frm, cdt, cdn) {
        _recompute_total_standard_cost(cdt, cdn);
    },

    custom_fg_items_remove(frm) {
        _recompute_multiply_by(frm);
    },
});

frappe.ui.form.on("Detox Production Plan Operation", {
    qty_per_unit(frm, cdt, cdn) {
        _recompute_one_multiply_by(frm, locals[cdt][cdn]);
    },
});

function _apply_no_bom_visibility(frm) {
    const on = !!frm.doc.custom_no_bom;
    // Standard sections we hide in No-BOM mode. Section names match the
    // ERPNext Production Plan layout — adjust if v16 renames any.
    const STANDARD_SECTIONS = [
        "get_items_from_section",
        "sales_orders",
        "material_requests",
        "material_request_section",
        "sales_order_section",
        "bom_section",
        "for_warehouse",
        "items_section",
    ];
    STANDARD_SECTIONS.forEach(fn => {
        if (frm.fields_dict[fn]) frm.toggle_display(fn, !on);
    });
    // Custom sections / tables visible only in No-BOM mode.
    ["custom_fg_items", "custom_operations"].forEach(fn => {
        if (frm.fields_dict[fn]) frm.toggle_display(fn, on);
    });
}

function _recompute_total_standard_cost(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row) return;
    const qty = flt(row.qty_to_manufacture);
    const rate = flt(row.standard_costing_rate);
    frappe.model.set_value(cdt, cdn, "total_standard_cost", qty * rate);
}

function _recompute_multiply_by(frm) {
    const fg = frm.doc.custom_fg_items || [];
    const sum_qty = fg.reduce((acc, r) => acc + flt(r.qty_to_manufacture), 0);
    (frm.doc.custom_operations || []).forEach(op => {
        const want = flt(op.qty_per_unit) * sum_qty;
        if (Math.abs(flt(op.multiply_by) - want) > 0.0001) {
            frappe.model.set_value(op.doctype, op.name, "multiply_by", want);
        }
    });
}

function _recompute_one_multiply_by(frm, op) {
    if (!op) return;
    const fg = frm.doc.custom_fg_items || [];
    const sum_qty = fg.reduce((acc, r) => acc + flt(r.qty_to_manufacture), 0);
    const want = flt(op.qty_per_unit) * sum_qty;
    if (Math.abs(flt(op.multiply_by) - want) > 0.0001) {
        frappe.model.set_value(op.doctype, op.name, "multiply_by", want);
    }
}
