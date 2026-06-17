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
        _lock_source_row_fields(frm);
        _wire_po_item_filter(frm);
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

// FR-11 — when the user picks a Purchase Order on a source row, restrict
// the PO Item picker to lines from THAT PO. Also point at the custom
// query so the autocomplete shows item_code instead of the row's hash
// name (Sahil Image #34).
function _wire_po_item_filter(frm) {
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (!grid || !grid.get_field) return;
    const po_item_field = grid.get_field("custom_purchase_order_item");
    if (!po_item_field) return;
    po_item_field.get_query = function (doc, cdt, cdn) {
        const row = locals[cdt] && locals[cdt][cdn];
        const filters = {};
        if (row && row.custom_purchase_order) {
            filters.parent = row.custom_purchase_order;
        }
        return {
            query: "detox_project.detox_project.overrides.stock_entry_manufacture.po_item_link_query",
            filters: filters,
        };
    };
}

// FR-09 — on Manufacture-flow SEs, source rows (rows with s_warehouse
// set) have item_code / uom / basic_rate / expense_account read-only;
// only qty stays editable. Target FG rows keep all fields editable
// for the user to enter what was actually produced.
function _lock_source_row_fields(frm) {
    if (!_is_mfg(frm)) return;
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (!grid || !grid.grid_rows) return;
    const LOCKED = ["item_code", "uom", "basic_rate", "expense_account"];
    grid.grid_rows.forEach((gr) => {
        const row = gr.doc;
        if (!row || !row.s_warehouse) return;
        LOCKED.forEach((fn) => {
            try { gr.toggle_editable(fn, false); } catch (e) { /* field absent */ }
        });
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
    // Whitelisted server method — bypasses client-side child-perm
    // walls on Detox Production Plan Process.
    frappe.call({
        method: "detox_project.detox_project.overrides.stock_entry_manufacture.get_plan_processes",
        args: {production_plan: frm.doc.production_plan},
        callback(r) {
            const rows = (r && r.message) || [];
            const seen = new Set();
            const opts = ["", ...rows.map((row) => row.operation_name).filter((n) => {
                if (!n || seen.has(n)) return false;
                seen.add(n);
                return true;
            })];
            if (frm.fields_dict.custom_process_selection) {
                frm.set_df_property("custom_process_selection", "options", opts.join("\n"));
                frm.refresh_field("custom_process_selection");
            }
        },
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
            // FR-09 — Clear any rows we previously auto-fetched. We tag
            // each fetched row with _auto_fetched so we can wipe them
            // on the next Process change without disturbing target FG
            // rows the user typed manually. Also clear empty placeholder
            // rows (no item_code) Frappe auto-adds to the grid.
            const survivors = (frm.doc.items || []).filter((row) => {
                if (row._auto_fetched) return false;
                if (!row.item_code) return false;  // empty placeholder
                return true;
            });
            // Rebuild the table from scratch — set the canonical array
            // back and let Frappe re-index.
            frm.doc.items = survivors;
            if (!rows.length) {
                frm.refresh_field("items");
                frappe.msgprint({
                    title: __("No materials found"),
                    message: __(
                        "No Materials / Service rows are defined for Operation "
                        + "'{0}' on the linked Production Plan. Add them on the "
                        + "plan first (per-Operation 'Add Material / Service Row' "
                        + "button), then re-pick the Process here.",
                        [frm.doc.custom_process_selection]
                    ),
                    indicator: "orange",
                });
                return;
            }
            rows.forEach((src) => {
                const item = frappe.model.add_child(frm.doc, "Stock Entry Detail", "items");
                item._auto_fetched = true;  // marker for the next clear
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
            // Lock the fetched source rows per FR-09.
            _lock_source_row_fields(frm);
            frappe.show_alert({
                message: __("Fetched {0} source row(s) for {1}.",
                            [rows.length, frm.doc.custom_process_selection]),
                indicator: "green",
            });
        },
    });
}
