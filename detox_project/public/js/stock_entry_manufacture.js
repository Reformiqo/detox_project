// ABP2-I419 Phase 3 (Sahil 2026-06-17, Out of BRD) — Stock Entry
// Manufacture client logic: L08 process auto-fetch, L09 source-row
// locking, L10 target defaults, L12 PO rate fetch, VAL-09 confirm-on-
// change of process when rows already exist.

const MFG_TYPES = new Set([
    "Manufacture",
    "Material Transfer for Manufacture",
    "Repack",
]);

frappe.ui.form.on("Stock Entry", {
    refresh(frm) {
        _apply_phase3_visibility(frm);
        _populate_process_options(frm);
    },

    stock_entry_type(frm) {
        _apply_phase3_visibility(frm);
    },

    production_plan(frm) {
        _populate_process_options(frm);
    },

    custom_process_selection(frm) {
        if (!_is_mfg(frm)) return;
        if (!frm.doc.production_plan) {
            frappe.msgprint(__("Pick a Production Plan first."));
            return;
        }
        if ((frm.doc.items || []).length > 0) {
            frappe.confirm(
                __("Changing the process will clear all source rows. Continue?"),
                () => _fetch_operation_rows(frm),
            );
        } else {
            _fetch_operation_rows(frm);
        }
    },
});

frappe.ui.form.on("Stock Entry Detail", {
    item_code(frm, cdt, cdn) {
        if (!_is_mfg(frm)) return;
        const row = locals[cdt][cdn];
        // L10 — for target FG rows, pull t_warehouse + basic_rate from
        // the plan's Table 1.
        if (row.is_finished_item && frm.doc.production_plan && row.item_code) {
            frappe.call({
                method: "detox_project.detox_project.overrides.stock_entry_manufacture.get_fg_defaults",
                args: {
                    production_plan: frm.doc.production_plan,
                    item_code: row.item_code,
                },
                callback(r) {
                    const d = (r && r.message) || {};
                    if (d.t_warehouse) {
                        frappe.model.set_value(cdt, cdn, "t_warehouse", d.t_warehouse);
                    }
                    if (d.basic_rate) {
                        frappe.model.set_value(cdt, cdn, "basic_rate", d.basic_rate);
                    }
                },
            });
        }
    },

    custom_purchase_order_item(frm, cdt, cdn) {
        if (!_is_mfg(frm)) return;
        const row = locals[cdt][cdn];
        if (!row.custom_purchase_order_item || !row.custom_purchase_order) return;
        // L12 — fetch the linked PO line's rate so the user can see the
        // actual procured rate next to the plan's standard_rate.
        frappe.db.get_value(
            "Purchase Order Item",
            row.custom_purchase_order_item,
            ["rate", "amount"],
            (r) => {
                if (r && r.rate) {
                    frappe.model.set_value(cdt, cdn, "additional_cost", flt(r.rate));
                }
            },
        );
    },
});

function _is_mfg(frm) {
    return MFG_TYPES.has(frm.doc.stock_entry_type || "");
}

function _apply_phase3_visibility(frm) {
    const on = _is_mfg(frm);
    ["custom_process_selection",
     "custom_production_time",
     "custom_time_uom"].forEach((fn) => {
        if (frm.fields_dict[fn]) frm.toggle_display(fn, on);
        if (frm.fields_dict[fn] && on && fn !== "custom_process_selection") {
            // Make production_time + time_uom mandatory for Manufacturing-flow SEs.
            frm.toggle_reqd(fn, true);
        }
    });
}

function _populate_process_options(frm) {
    if (!frm.doc.production_plan) {
        if (frm.fields_dict.custom_process_selection) {
            frm.set_df_property("custom_process_selection", "options", "");
            frm.refresh_field("custom_process_selection");
        }
        return;
    }
    // Get unique operation names from the linked plan's Table 2.
    frappe.db.get_list("Detox Production Plan Operation", {
        filters: {
            parent: frm.doc.production_plan,
            parenttype: "Production Plan",
        },
        fields: ["operation_name"],
        limit: 100,
    }).then((rows) => {
        const seen = new Set();
        const opts = ["", ...rows.map((r) => r.operation_name).filter((n) => {
            if (!n || seen.has(n)) return false;
            seen.add(n);
            return true;
        })];
        if (frm.fields_dict.custom_process_selection) {
            frm.set_df_property("custom_process_selection", "options", opts.join("\n"));
            frm.refresh_field("custom_process_selection");
        }
    });
}

function _fetch_operation_rows(frm) {
    frappe.call({
        method: "detox_project.detox_project.overrides.stock_entry_manufacture.get_operation_rm_rows",
        args: {
            production_plan: frm.doc.production_plan,
            operation: frm.doc.custom_process_selection,
        },
        callback(r) {
            const rows = (r && r.message) || [];
            // Remove existing SOURCE rows (rows with s_warehouse). Keep
            // target FG rows the user already typed.
            frm.doc.items = (frm.doc.items || []).filter((row) => !row.s_warehouse);
            rows.forEach((src) => {
                const item = frappe.model.add_child(frm.doc, "Stock Entry Detail", "items");
                item.item_code = src.item_code;
                item.item_name = src.item_name;
                item.uom = src.uom;
                item.stock_uom = src.stock_uom;
                item.basic_rate = src.basic_rate;
                item.qty = 0;
                item.cost_center = src.cost_center;
                item.project = src.project;
                if (src.expense_account) item.expense_account = src.expense_account;
                if (frm.doc.from_warehouse) item.s_warehouse = frm.doc.from_warehouse;
            });
            frm.refresh_field("items");
            frappe.show_alert({
                message: __("Fetched {0} source row(s) for {1}.",
                            [rows.length, frm.doc.custom_process_selection]),
                indicator: "green",
            });
        },
    });
}
