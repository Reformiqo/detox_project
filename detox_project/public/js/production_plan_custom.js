// ABP2-I419 Production Plan client logic for No-BOM mode.
// eslint-disable-next-line no-console
console.log("[ABP2-I782] production_plan_custom.js loaded");

//
// Layers (cumulative):
//   Phase 1 — No-BOM toggle, total_standard_cost, Multiply By,
//             standard_costing_rate pre-fill.
//   Phase 7 — Processes (Operation + Workstation) header table +
//             read-only Operations Breakdown HTML field.
//   Phase 7b — Operation columns linked to ERPNext Operation master.
//   Phase 7c (rolled back 7d) — was: autosync + uniqueness.
//   Phase 7d — Sahil 2026-06-17 (Image #9): per-operation EDITABLE
//             card tables. Canonical custom_operations grid hidden;
//             one card per Process row drives add/edit/delete via
//             Frappe Dialog modals.
//   9f14c2d/710a98a (Sanket, Aug 2026) — Budget Category (budget_category,
//             get_project_budget_categories), item-level UOM conversion
//             (detox_project.api.get_item_uom_factor) wired into the
//             dialog's manual_uom onchange + get_operation_rm_rows.
//   f927e62 (Sanket, Aug 2026) — every Table 2 field allow_on_submit=1 +
//             post-submit CC/Project re-guard (cc_project_guard.py).
//   ABP2-I782 (2026-10-05) — "Multiply By" removed: each row now stands
//             alone (Qty x rate = Amount, no Finished Goods qty
//             involved). Manual UOM change recalculates the effective
//             rate via get_uom_factor (item-level UOM data first, global
//             Month/Day/Hour + TON/Tonne master fallback second — see
//             change_set/abp2_i782_fixlist.py). Project Budget (read-only
//             Financial Model display, NOT the same thing as Budget
//             Category above) added.

frappe.ui.form.on("Production Plan", {
    onload(frm) {
        _apply_no_bom_visibility(frm);
        _refresh_operation_options(frm);
        _sync_project_into_proxy(frm);
    },

    refresh(frm) {
        _apply_no_bom_visibility(frm);
        _refresh_operation_options(frm);
        _render_per_operation_cards(frm);
        _sync_project_into_proxy(frm);
        _add_stock_entry_button(frm);
    },

    custom_no_bom(frm) {
        _apply_no_bom_visibility(frm);
        _render_per_operation_cards(frm);
    },

    custom_cost_center(frm) {
        _render_per_operation_cards(frm);
    },

    // Sahil Image #16 — custom_project is the user-facing proxy field
    // sitting next to Cost Center. Push its value into the native
    // doc.project so the reqd=1 (Phase 1) + validate hook (Phase 2)
    // accept the value on save.
    custom_project(frm) {
        if (frm.doc.custom_project !== frm.doc.project) {
            // set_value("project", ...) below fires the "project" handler,
            // which does the actual budget fetch (ABP2-I782) — one place,
            // no duplicate frappe.call.
            frm.set_value("project", frm.doc.custom_project);
        }
        _render_per_operation_cards(frm);
    },

    project(frm) {
        // Mirror back so the proxy stays in sync if anything (e.g. an
        // older bookmarked link, an integration) sets doc.project.
        if (frm.doc.project !== frm.doc.custom_project) {
            frm.set_value("custom_project", frm.doc.project);
        }
        _fetch_project_budget(frm);
        _render_per_operation_cards(frm);
    },
});

// ABP2-I782 req #4 — Project Budget (read-only display). Fetched only on
// the `project` field's OWN change event (user picking/changing the
// Project), never on refresh/onload — refetching on every refresh would
// call frm.set_value on an already-saved/submitted doc just from opening
// it, marking it dirty for no reason. Pre-ABP2-I782 Production Plans that
// already have a Project but predate this fix simply show blank budget
// fields until the Project is reselected; display-only, no calculation
// depends on it, so that's an acceptable gap (confirmed with the manager).
// NOT the same thing as 9f14c2d's "Budget Category" (budget_category on
// Table 2 rows, Project Cost Category) — this is a header-level display
// of the Financial Model itself.
function _fetch_project_budget(frm) {
    if (!frm.fields_dict.custom_project_budget) return;  // CF not migrated yet
    if (!frm.doc.project) {
        frm.set_value("custom_project_budget", "");
        frm.set_value("custom_budget_type", "");
        frm.set_value("custom_budget_start_date", "");
        frm.set_value("custom_budget_end_date", "");
        return;
    }
    frappe.call({
        method: "detox_project.detox_project.change_set.abp2_i782_fixlist.get_approved_financial_model",
        args: {project: frm.doc.project},
        callback(r) {
            const d = (r && r.message) || {};
            frm.set_value("custom_project_budget", d.project_budget || "");
            frm.set_value("custom_budget_type", d.budget_type || "");
            frm.set_value("custom_budget_start_date", d.budget_start_date || "");
            frm.set_value("custom_budget_end_date", d.budget_end_date || "");
        },
    });
}

function _sync_project_into_proxy(frm) {
    if (frm.doc.project && frm.doc.project !== frm.doc.custom_project) {
        frm.set_value("custom_project", frm.doc.project);
    } else if (frm.doc.custom_project && !frm.doc.project) {
        frm.set_value("project", frm.doc.custom_project);
    }
}

// FRD FR-07 + Sahil Image #17 — on a SUBMITTED No-BOM Production Plan,
// add a 'Stock Entry' button under the Create menu that opens a fresh
// Manufacture Stock Entry pre-filled with production_plan + company +
// CC + project. Phase 3's stock_entry_manufacture.js takes it from
// there: process_selection auto-fetches the operation's source rows.
function _add_stock_entry_button(frm) {
    if (frm.is_new()) return;
    if (frm.doc.docstatus !== 1) return;
    if (!frm.doc.custom_no_bom) return;

    frm.add_custom_button(__("Stock Entry"), () => {
        const new_se = frappe.model.get_new_doc("Stock Entry");
        new_se.stock_entry_type = "Manufacture";
        new_se.production_plan = frm.doc.name;
        new_se.company = frm.doc.company;
        // SE refactor (2026-06-26): Production Plan keeps custom_cost_center
        // but Stock Entry now uses the standard cost_center field.
        if (frm.doc.custom_cost_center) {
            new_se.cost_center = frm.doc.custom_cost_center;
        }
        if (frm.doc.project) {
            new_se.project = frm.doc.project;
        }
        // Default the source warehouse to the first FG row's warehouse
        // (best-effort; user can override).
        const first_fg = (frm.doc.custom_fg_items || [])[0];
        if (first_fg && first_fg.fg_warehouse) {
            new_se.from_warehouse = first_fg.fg_warehouse;
        }
        frappe.set_route("Form", "Stock Entry", new_se.name);
    }, __("Create"));

    _add_material_transfer_button(frm);
}

// CR-04 / CL-13 — on a SUBMITTED No-BOM Production Plan, add a
// 'Material Transfer for Manufacture' button under Create. The user
// picks the operation; the server builder (CZ-40) pulls that operation's
// Table-2 raw-material rows and returns a DRAFT Stock Entry of type
// 'Material Transfer for Manufacture' with company / cost_center /
// project inherited. Mirrors _add_stock_entry_button but the row build
// is server-side so it can reuse get_operation_rm_rows.
function _add_material_transfer_button(frm) {
    if (frm.is_new()) return;
    if (frm.doc.docstatus !== 1) return;
    if (!frm.doc.custom_no_bom) return;

    frm.add_custom_button(__("Material Transfer for Manufacture"), () => {
        // Operation options come from the plan's declared operations
        // (custom_operations) / processes (custom_processes) — distinct
        // operation_name values.
        const seen = {};
        const ops = [];
        (frm.doc.custom_processes || []).concat(frm.doc.custom_operations || [])
            .forEach((r) => {
                const op = r.operation_name;
                if (op && !seen[op]) { seen[op] = 1; ops.push(op); }
            });
        if (!ops.length) {
            frappe.msgprint({
                title: __("No operations"),
                message: __("This plan has no operations to transfer for."),
                indicator: "orange",
            });
            return;
        }
        frappe.prompt(
            [{
                fieldname: "operation",
                label: __("Operation / Process"),
                fieldtype: "Select",
                options: ops.join("\n"),
                default: ops[0],
                reqd: 1,
            }],
            (values) => {
                frappe.call({
                    method: "detox_project.detox_project.change_set."
                        + "cr04_material_transfer.make_material_transfer_for_manufacture",
                    args: {
                        production_plan: frm.doc.name,
                        operation: values.operation,
                    },
                    freeze: true,
                    freeze_message: __("Building Material Transfer…"),
                    callback(r) {
                        if (!r || !r.message) return;
                        const doc = frappe.model.sync(r.message)[0];
                        frappe.set_route("Form", "Stock Entry", doc.name);
                    },
                });
            },
            __("Material Transfer for Manufacture"),
            __("Create")
        );
    }, __("Create"));
}

frappe.ui.form.on("Detox Production Plan Process", {
    operation_name(frm) {
        _refresh_operation_options(frm);
        _render_per_operation_cards(frm);
    },
    workstation(frm) {
        _render_per_operation_cards(frm);
    },
    custom_processes_remove(frm) {
        _refresh_operation_options(frm);
        _remove_orphan_materials(frm);
        _render_per_operation_cards(frm);
    },
});

frappe.ui.form.on("Detox Production Plan FG", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.item_code) return;
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
        // ABP2-I782 — Table 1 (Finished Goods) qty no longer feeds Table 2
        // row amounts at all ("Multiply By" removal, req #1). Only this
        // row's own total_standard_cost (FG costing, unrelated table) uses it.
        _recompute_total_standard_cost(cdt, cdn);
    },

    standard_costing_rate(frm, cdt, cdn) {
        _recompute_total_standard_cost(cdt, cdn);
    },
});

frappe.ui.form.on("Detox Production Plan Operation", {
    qty(frm, cdt, cdn) {
        _recompute_row_amount(frm, locals[cdt][cdn]);
        _render_per_operation_cards(frm);
    },
    standard_rate(frm, cdt, cdn) {
        _recompute_row_amount(frm, locals[cdt][cdn]);
        _render_per_operation_cards(frm);
    },
    manual_uom(frm, cdt, cdn) {
        // ABP2-I782 req #3 — UOM change recalculates the effective rate
        // (e.g. ₹27,000/Month -> ₹900/Day), not just the Amount. Grid-row
        // counterpart of the dialog's manual_uom onchange below.
        _recompute_row_amount(frm, locals[cdt][cdn]);
        _render_per_operation_cards(frm);
    },
    custom_operations_add(frm, cdt, cdn) {
        // New rows default Qty to 1 per req #1 ("each row stands alone").
        // The docfield `default: "1"` covers inserts via the canonical
        // grid; the Phase 7d dialog (_open_material_dialog) sets it too.
        const row = locals[cdt][cdn];
        if (!row.qty) frappe.model.set_value(cdt, cdn, "qty", 1);
    },
    custom_operations_remove(frm) {
        _render_per_operation_cards(frm);
    },
});

// ABP2-I782 req #1 + #3 — Amount = Qty x effective rate. Effective rate is
// Standard Rate unless Manual UOM is set and differs from Standard UOM, in
// which case get_uom_factor_api is consulted (item-level UOM Conversion
// Detail first, global Month/Day/Hour + TON/Tonne master fallback second —
// see change_set.abp2_i782_fixlist.get_uom_factor) and the rate is
// MULTIPLIED by that factor (factor = "how many Standard UOM per 1 Manual
// UOM", same direction detox_project.api.get_item_uom_factor already
// uses — e.g. ₹27,000/Month x 1/30 = ₹900/Day). Mirrors
// change_set.abp2_i782_fixlist._effective_rate() — kept in sync manually
// since client/server can't share Python; both are covered by
// test_abp2_i782_production_plan_uom.py.
function _recompute_row_amount(frm, row) {
    if (!row) return;
    const qty = flt(row.qty) || 1;
    const std_rate = flt(row.standard_rate);
    const std_uom = row.standard_uom;
    const man_uom = row.manual_uom;
    const apply = (rate, factor) => {
        frappe.model.set_value(row.doctype, row.name, "conversion_factor", factor || 0);
        frappe.model.set_value(row.doctype, row.name, "amount", flt(qty * rate));
        _render_per_operation_cards(frm);
    };
    if (!man_uom || man_uom === std_uom || !row.item_code) {
        apply(std_rate, null);
        return;
    }
    frappe.call({
        method: "detox_project.detox_project.change_set.abp2_i782_fixlist.get_uom_factor_api",
        args: {item_code: row.item_code, uom: man_uom},
        callback(r) {
            const factor = r && r.message;
            if (factor) {
                apply(flt(std_rate * factor), factor);
            } else {
                // No conversion found anywhere (item-level or global
                // master) — don't guess (ticket's own instruction). Keep
                // Amount on the raw Standard Rate and tell the user why,
                // instead of silently using the wrong number like the
                // original "Multiply By" bug did.
                apply(std_rate, null);
                frappe.show_alert({
                    message: __("No UOM conversion found for {0} on {1} (checked Item UOMs and the global UOM Conversion Factor master) — Amount uses Standard Rate as-is.", [man_uom, row.item_code]),
                    indicator: "orange",
                });
            }
        },
    });
}

// --------------------------------------------------------------------------
// Visibility + simple computations (Phase 1)
// --------------------------------------------------------------------------
function _apply_no_bom_visibility(frm) {
    const on = !!frm.doc.custom_no_bom;
    const STANDARD_SECTIONS = [
        "get_items_from_section",
        "sales_orders",
        "material_requests",
        "material_request_section",
        "sales_order_section",
        "bom_section",
        "for_warehouse",
        "items_section",
        "select_items_to_manufacture",
        "assembly_items",
        "sub_assembly_items",
    ];
    STANDARD_SECTIONS.forEach(fn => {
        if (!frm.fields_dict[fn]) return;
        frm.set_df_property(fn, "hidden", on ? 1 : 0);
        frm.toggle_display(fn, !on);
    });
    // Custom Production Plan sections / tables: shown only in No-BOM mode.
    ["custom_fg_items", "custom_processes",
     "custom_operations_view"].forEach(fn => {
        if (!frm.fields_dict[fn]) return;
        frm.set_df_property(fn, "hidden", on ? 0 : 1);
        frm.toggle_display(fn, on);
    });
    // Phase 7d — hide the canonical custom_operations grid in No-BOM mode;
    // the per-operation cards drive add/edit/delete. Hide both the field
    // and (in No-BOM mode) the section wrapper around it.
    if (frm.fields_dict.custom_operations) {
        frm.set_df_property("custom_operations", "hidden", on ? 1 : 0);
        frm.toggle_display("custom_operations", !on);
    }
    if (frm.fields_dict.custom_operations_section) {
        // Keep the section header visible in No-BOM mode so the per-
        // operation cards have something to anchor under; hide it
        // entirely in BOM mode.
        frm.set_df_property("custom_operations_section", "hidden", on ? 0 : 1);
        frm.toggle_display("custom_operations_section", on);
    }
}

function _recompute_total_standard_cost(cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row) return;
    const qty = flt(row.qty_to_manufacture);
    const rate = flt(row.standard_costing_rate);
    frappe.model.set_value(cdt, cdn, "total_standard_cost", qty * rate);
}

// ABP2-I782 — _fg_total_qty / _recompute_multiply_by / _recompute_one_multiply_by
// (f927e62's Table-1-qty-driven "Multiply By" engine) deleted here: once no
// row calculation multiplies by Finished Goods quantity (req #1), nothing
// in this file needs "the multiplier behind every row" anymore. The dialog's
// qty_per_unit preview that called these is removed too (see
// _open_material_dialog below).

function _refresh_operation_options(frm) {
    const grid = frm.fields_dict.custom_operations && frm.fields_dict.custom_operations.grid;
    if (!grid) return;
    const allowed = (frm.doc.custom_processes || [])
        .map(p => p.operation_name)
        .filter(Boolean);
    grid.get_field("operation_name").get_query = function () {
        if (!allowed.length) return {};
        return {filters: {name: ["in", allowed]}};
    };
}

// --------------------------------------------------------------------------
// Phase 7d — Per-Operation editable cards
// --------------------------------------------------------------------------

const _MAT_FIELDS = [
    {fieldname: "item_code", label: __("Item Code"), fieldtype: "Link",
     options: "Item", reqd: 1, in_list_view: true},
    {fieldname: "item_type", label: __("Item Type"), fieldtype: "Select",
     options: "Raw Material\nService", reqd: 1, in_list_view: true},
    {fieldname: "standard_uom", label: __("Standard UOM"), fieldtype: "Link",
     options: "UOM", read_only: 1, fetch_from: "item_code.stock_uom"},
    {fieldname: "manual_uom", label: __("Manual UOM"), fieldtype: "Link",
     options: "UOM"},
    {fieldname: "standard_rate", label: __("Standard Rate"),
     fieldtype: "Currency", reqd: 1, in_list_view: true},
    // ABP2-I782 — Qty replaces Multiply By: this row stands alone
    // (Qty x effective rate = Amount), default 1, no FG multiplication.
    {fieldname: "qty", label: __("Qty"), fieldtype: "Float",
     default: 1, in_list_view: true},
    {fieldname: "amount", label: __("Amount"), fieldtype: "Currency",
     read_only: 1, in_list_view: true},
    // ABP2-I782 walkthrough fix — Conversion Factor was computed and saved
    // correctly but had no UI surface anywhere on this dialog/table (full-
    // text search found 0 matches). Read-only, precision 6 since the
    // value is typically a fraction (e.g. 1/30 = 0.033333 for Month->Day
    // — "how many Standard UOM per 1 Manual UOM", get_item_uom_factor's
    // own convention; NOT literally "30").
    {fieldname: "conversion_factor", label: __("Conversion Factor"),
     fieldtype: "Float", precision: 6, read_only: 1, in_list_view: true},
    {fieldname: "qty_per_unit", label: __("Qty per Unit (reference only)"),
     fieldtype: "Float"},
    {fieldname: "operation_seq", label: __("Operation Seq"), fieldtype: "Int"},
    {fieldname: "subcontract_section", label: __("Subcontracting"),
     fieldtype: "Section Break", collapsible: 1},
    {fieldname: "is_subcontracted", label: __("Is Subcontracted"),
     fieldtype: "Check", default: 0},
    {fieldname: "subcontractor", label: __("Subcontractor"), fieldtype: "Link",
     options: "Supplier", depends_on: "is_subcontracted",
     mandatory_depends_on: "eval:doc.is_subcontracted"},
    {fieldname: "service_item", label: __("Service Item"), fieldtype: "Link",
     options: "Item", depends_on: "is_subcontracted",
     mandatory_depends_on: "eval:doc.is_subcontracted"},
    // Service PO is OPTIONAL on subcontracted rows (Sahil 2026-06-17 Image #13).
    // The user can attach the Service PO later once it's raised.
    {fieldname: "service_po", label: __("Service PO"), fieldtype: "Link",
     options: "Purchase Order", depends_on: "is_subcontracted"},
    {fieldname: "return_item", label: __("Return Item"), fieldtype: "Link",
     options: "Item", depends_on: "is_subcontracted",
     mandatory_depends_on: "eval:doc.is_subcontracted"},
    {fieldname: "dim_section", label: __("Cost Center & Project"),
     fieldtype: "Section Break"},
    {fieldname: "cost_center", label: __("Cost Center"), fieldtype: "Link",
     options: "Cost Center", reqd: 1},
    {fieldname: "project", label: __("Project"), fieldtype: "Link",
     options: "Project", reqd: 1},
    // Filtered to the Project's Financial Model — see get_query below.
    {fieldname: "budget_category", label: __("Budget Category"),
     fieldtype: "Link", options: "Project Cost Category"},
];

function _render_per_operation_cards(frm) {
    const wrap = frm.fields_dict.custom_operations_view
              && frm.fields_dict.custom_operations_view.$wrapper;
    if (!wrap) return;
    if (!frm.doc.custom_no_bom) {
        wrap.find(".phase7d-cards").remove();
        return;
    }

    const escape = (s) => frappe.utils.escape_html(String(s == null ? "" : s));
    const processes = frm.doc.custom_processes || [];
    const ops = frm.doc.custom_operations || [];

    if (!processes.length) {
        wrap.find(".phase7d-cards").remove();
        wrap.append(`<div class='phase7d-cards text-muted'
            style='margin-top:8px;padding:10px;border:1px dashed #ddd;border-radius:4px'>
            ${__("Add a row in <b>Processes</b> above to define an Operation. "
            + "An editable Materials table will appear for each Operation.")}
        </div>`);
        return;
    }

    const buckets = new Map();
    processes.forEach(p => {
        if (!p.operation_name) return;
        buckets.set(p.operation_name, {
            workstation: p.workstation || "",
            rows: [],
        });
    });
    const orphans = [];
    ops.forEach(o => {
        const key = o.operation_name;
        if (key && buckets.has(key)) buckets.get(key).rows.push(o);
        else orphans.push(o);
    });

    let html = "<div class='phase7d-cards'>";
    buckets.forEach((bucket, opName) => {
        html += _render_operation_card(opName, bucket);
    });
    if (orphans.length) {
        html += `<div style='margin:14px 0 6px 0;color:#dc3545;font-weight:600'>
            ${__("Unassigned rows (Operation not in Processes)")}
        </div>` + _render_rows_table(orphans);
    }
    html += "</div>";

    wrap.find(".phase7d-cards").remove();
    const $cards = $(html).appendTo(wrap);

    // Wire buttons.
    $cards.find("[data-action='add-row']").on("click", function () {
        const op = $(this).data("operation");
        _open_material_dialog(frm, op, null);
    });
    $cards.find("[data-action='edit-row']").on("click", function () {
        const op = $(this).data("operation");
        const name = $(this).data("name");
        const row = (frm.doc.custom_operations || []).find(r => r.name === name);
        if (row) _open_material_dialog(frm, op, row);
    });
    $cards.find("[data-action='delete-row']").on("click", function () {
        const name = $(this).data("name");
        const row = (frm.doc.custom_operations || []).find(r => r.name === name);
        if (!row) return;
        frappe.confirm(
            __("Delete this Materials row?"),
            () => {
                frm.doc.custom_operations = (frm.doc.custom_operations || [])
                    .filter(r => r.name !== name);
                frm.refresh_field("custom_operations");
                _render_per_operation_cards(frm);
                frm.dirty();
            }
        );
    });
}

function _render_operation_card(opName, bucket) {
    const escape = (s) => frappe.utils.escape_html(String(s == null ? "" : s));
    const ws = bucket.workstation ? escape(bucket.workstation) : "<em>—</em>";
    return `
        <div style='margin:18px 0 8px 0;padding:8px 12px;background:#f8f9fa;border-left:3px solid #2490ef;border-radius:3px'>
            <div style='font-weight:600;font-size:14px'>${escape(opName)}</div>
            <div class='text-muted' style='font-size:12px'>${__("Workstation")}: ${ws}</div>
        </div>
        ${_render_rows_table(bucket.rows, opName)}
        <div style='margin:6px 0 14px 0'>
            <button class='btn btn-xs btn-primary'
                    data-action='add-row' data-operation='${escape(opName)}'>
                + ${__("Add Material / Service Row")}
            </button>
        </div>
    `;
}

function _render_rows_table(rows, opName) {
    if (!rows.length) {
        return `<div class='text-muted' style='font-size:12px;padding:6px 0'>
            ${__("No materials / services added yet.")}
        </div>`;
    }
    const escape = (s) => frappe.utils.escape_html(String(s == null ? "" : s));
    const formatNum = (n) => {
        const v = parseFloat(n || 0);
        return v.toLocaleString(undefined, {maximumFractionDigits: 2});
    };
    const fmtCheck = (v) => v ? __("Yes") : __("No");
    // ABP2-I782 walkthrough fix — Conversion Factor is typically a small
    // fraction (e.g. 1/30 = 0.033333 for Month->Day), not a whole number
    // like Multiply By used to be — formatNum's 2-decimal rounding would
    // display it as "0.03", losing the precision that makes the value
    // legible. 6 decimals, em-dash when unset (same UOM, no conversion).
    const formatConvFactor = (n) => {
        const v = parseFloat(n || 0);
        return v ? v.toLocaleString(undefined, {maximumFractionDigits: 6}) : "—";
    };

    const trs = rows.map(r => `
        <tr>
            <td>${escape(r.item_code)}</td>
            <td>${escape(r.item_type)}</td>
            <td>${r.budget_category ? escape(r.budget_category) : "<em>—</em>"}</td>
            <td>${escape(r.standard_uom || r.manual_uom)}</td>
            <td class='text-right'>${formatNum(r.standard_rate)}</td>
            <td class='text-right'>${formatConvFactor(r.conversion_factor)}</td>
            <td class='text-right'>${formatNum(r.qty)}</td>
            <td class='text-right'>${formatNum(r.amount)}</td>
            <td>${fmtCheck(r.is_subcontracted)}</td>
            <td class='text-right' style='white-space:nowrap'>
                <button class='btn btn-xs btn-default'
                        data-action='edit-row'
                        data-operation='${escape(opName || r.operation_name || "")}'
                        data-name='${escape(r.name)}'>${__("Edit")}</button>
                <button class='btn btn-xs btn-danger'
                        data-action='delete-row'
                        data-name='${escape(r.name)}'>${__("Delete")}</button>
            </td>
        </tr>
    `).join("");

    return `
        <table class='table table-bordered' style='font-size:12px;margin-bottom:6px'>
            <thead style='background:#f1f3f5'>
                <tr>
                    <th>${__("Item")}</th>
                    <th>${__("Type")}</th>
                    <th>${__("Budget Category")}</th>
                    <th>${__("UOM")}</th>
                    <th class='text-right'>${__("Std Rate")}</th>
                    <th class='text-right'>${__("Conv. Factor")}</th>
                    <th class='text-right'>${__("Qty")}</th>
                    <th class='text-right'>${__("Amount")}</th>
                    <th>${__("Subc.")}</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>${trs}</tbody>
        </table>
    `;
}

function _open_material_dialog(frm, opName, existing_row) {
    const is_edit = !!existing_row;
    const d = new frappe.ui.Dialog({
        title: is_edit
            ? __("Edit Material / Service — {0}", [opName])
            : __("Add Material / Service — {0}", [opName]),
        fields: _MAT_FIELDS.map(f => ({...f})),
        size: "large",
        primary_action_label: is_edit ? __("Save") : __("Add"),
        primary_action(values) {
            let row = existing_row;
            if (!row) {
                row = frappe.model.add_child(
                    frm.doc, "Detox Production Plan Operation", "custom_operations");
            }
            row.operation_name = opName;
            _MAT_FIELDS.forEach(f => {
                if (!f.fieldname || f.fieldtype === "Section Break"
                    || f.fieldtype === "Column Break"
                    || f.fieldname === "amount" || f.fieldname === "conversion_factor") return;
                row[f.fieldname] = values[f.fieldname];
            });
            if (!row.qty) row.qty = 1;  // ABP2-I782 — "each row stands alone", default 1
            // ABP2-I782 — Amount = Qty x effective rate (was: pre-fill
            // multiply_by from Phase 1 FG-multiplication logic).
            _recompute_row_amount(frm, row);
            frm.refresh_field("custom_operations");
            _render_per_operation_cards(frm);
            frm.dirty();
            d.hide();
        },
    });

    // Budget Category → only the categories on this Project's Financial
    // Model. Read the project lazily so it follows the dialog's own field.
    if (d.fields_dict.budget_category) {
        d.fields_dict.budget_category.get_query = () => ({
            query: "detox_project.detox_project.api.get_project_budget_categories",
            filters: {project: d.get_value("project")},
        });
    }

    // Manual UOM → ABP2-I782: was a hard-throw ("UOM X is not set on Item
    // Y...") whenever the Item had no UOM Conversion Detail row for this
    // UOM — exactly the ticket's own complaint case ("Items have only one
    // UOM... Supply of Labour = Month only"). Now composes get_uom_factor
    // (item-level first, global Month/Day/Hour + TON/Tonne master
    // fallback second) and previews the Amount live; only throws if
    // NEITHER source resolves a factor at all.
    if (d.fields_dict.manual_uom) {
        d._last_uom = (existing_row && existing_row.manual_uom) || "";
        d.fields_dict.manual_uom.df.onchange = () => {
            const item_code = d.get_value("item_code");
            const uom = d.get_value("manual_uom");
            // Dialog Link fields fire onchange twice (awesomplete select,
            // then blur) — frappe's own guards need a frm/doc, which a
            // Dialog has neither of. Also skips the prefill on edit.
            if (!item_code || !uom || uom === d._last_uom) return;
            d._last_uom = uom;
            const std_uom = d.get_value("standard_uom");
            if (uom === std_uom) {
                d.set_value("conversion_factor", 0);
                d.set_value("amount", flt(d.get_value("qty") || 1) * flt(d.get_value("standard_rate")));
                return;
            }
            frappe.call({
                method: "detox_project.detox_project.change_set.abp2_i782_fixlist.get_uom_factor_api",
                args: {item_code: item_code, uom: uom},
            }).then(r => {
                // Stale-response guard: the user may have changed Manual
                // UOM again (or closed the dialog) before this resolved —
                // don't stomp a newer value with an old async response.
                if (!d.fields_dict.manual_uom || d.get_value("manual_uom") !== uom) return;
                const factor = r && r.message;
                if (!factor) {
                    // frappe.throw() expects a synchronous validate-style
                    // call stack to attach its error dialog to; calling it
                    // from inside a resolved Promise has no such stack, so
                    // it only produces a silent unhandled-rejection in the
                    // console instead of the intended user-facing message.
                    // frappe.msgprint is the correct call from an async
                    // context — it does not depend on being inside a
                    // try/catch frappe itself controls.
                    frappe.msgprint({
                        title: __("No UOM conversion found"),
                        message: __("No UOM conversion found for {0} on Item {1} (checked the Item's own UOMs and the global UOM Conversion Factor master). Add one in the Item's UOM table, or in UOM Conversion Factor.",
                                    [uom, item_code]),
                        indicator: "red",
                    });
                    d.set_value("conversion_factor", 0);
                    return;
                }
                const qty = flt(d.get_value("qty")) || 1;
                const rate = flt(d.get_value("standard_rate")) * factor;
                d.set_value("conversion_factor", factor);
                d.set_value("amount", flt(qty * rate));
            });
        };
    }

    // Item Code → fetch Item.stock_uom into Standard UOM. Dialog fields
    // don't honour the docfield-level `fetch_from`; do it explicitly.
    // Pre-existing async pattern (not changed by ABP2-I782's logic), but
    // hardened with the same stale-response guard as manual_uom above
    // while investigating the walkthrough's "reading 'fields_dict'"
    // console error — both handlers do an async frappe call then touch
    // `d` afterwards, so both get the guard rather than guessing which
    // one is the actual source.
    if (d.fields_dict.item_code) {
        d.fields_dict.item_code.df.onchange = () => {
            const code = d.get_value("item_code");
            if (!code) return;
            frappe.db.get_value("Item", code, "stock_uom").then(r => {
                if (!d.fields_dict.item_code || d.get_value("item_code") !== code) return;
                const uom = r && r.message && r.message.stock_uom;
                if (uom) d.set_value("standard_uom", uom);
            });
        };
    }

    // Pre-fill values.
    if (existing_row) {
        const vals = {};
        _MAT_FIELDS.forEach(f => {
            if (f.fieldname && existing_row[f.fieldname] != null) {
                vals[f.fieldname] = existing_row[f.fieldname];
            }
        });
        d.set_values(vals);
    } else {
        d.set_values({
            cost_center: frm.doc.custom_cost_center,
            project: frm.doc.project,
            item_type: "Raw Material",
            qty: 1,
        });
    }
    d.show();
}

function _remove_orphan_materials(frm) {
    const valid_ops = new Set(
        (frm.doc.custom_processes || [])
            .map(p => p.operation_name)
            .filter(Boolean)
    );
    const before = (frm.doc.custom_operations || []).slice();
    const remaining = before.filter(o => !o.operation_name || valid_ops.has(o.operation_name));
    if (remaining.length === before.length) return;
    const removed = before.length - remaining.length;
    frm.doc.custom_operations = remaining;
    frm.refresh_field("custom_operations");
    frappe.show_alert({
        message: __("Removed {0} Materials row(s) whose Operation is no longer in Processes.", [removed]),
        indicator: "orange",
    });
    frm.dirty();
}
