// ABP2-I419 Production Plan client logic for No-BOM mode.
// eslint-disable-next-line no-console
console.log("[ABP2-I419] production_plan_custom.js Phase 7d loaded");

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

frappe.ui.form.on("Production Plan", {
    onload(frm) {
        _apply_no_bom_visibility(frm);
        _refresh_operation_options(frm);
        _sync_project_into_proxy(frm);
    },

    refresh(frm) {
        _apply_no_bom_visibility(frm);
        _recompute_multiply_by(frm);
        _refresh_operation_options(frm);
        _render_per_operation_cards(frm);
        _sync_project_into_proxy(frm);
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
        _render_per_operation_cards(frm);
    },
});

function _sync_project_into_proxy(frm) {
    if (frm.doc.project && frm.doc.project !== frm.doc.custom_project) {
        frm.set_value("custom_project", frm.doc.project);
    } else if (frm.doc.custom_project && !frm.doc.project) {
        frm.set_value("project", frm.doc.custom_project);
    }
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
        _recompute_total_standard_cost(cdt, cdn);
        _recompute_multiply_by(frm);
        _render_per_operation_cards(frm);
    },

    standard_costing_rate(frm, cdt, cdn) {
        _recompute_total_standard_cost(cdt, cdn);
    },

    custom_fg_items_remove(frm) {
        _recompute_multiply_by(frm);
        _render_per_operation_cards(frm);
    },
});

frappe.ui.form.on("Detox Production Plan Operation", {
    qty_per_unit(frm, cdt, cdn) {
        _recompute_one_multiply_by(frm, locals[cdt][cdn]);
        _render_per_operation_cards(frm);
    },
    custom_operations_remove(frm) {
        _render_per_operation_cards(frm);
    },
});

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
    {fieldname: "qty_per_unit", label: __("Qty per Unit"), fieldtype: "Float",
     in_list_view: true},
    {fieldname: "multiply_by", label: __("Multiply By"), fieldtype: "Float",
     read_only: 1, in_list_view: true},
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

    const trs = rows.map(r => `
        <tr>
            <td>${escape(r.item_code)}</td>
            <td>${escape(r.item_type)}</td>
            <td>${escape(r.standard_uom || r.manual_uom)}</td>
            <td class='text-right'>${formatNum(r.standard_rate)}</td>
            <td class='text-right'>${formatNum(r.qty_per_unit)}</td>
            <td class='text-right'>${formatNum(r.multiply_by)}</td>
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
                    <th>${__("UOM")}</th>
                    <th class='text-right'>${__("Std Rate")}</th>
                    <th class='text-right'>${__("Qty / Unit")}</th>
                    <th class='text-right'>${__("Multiply By")}</th>
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
                    || f.fieldtype === "Column Break") return;
                row[f.fieldname] = values[f.fieldname];
            });
            // Pre-fill multiply_by from Phase 1 logic.
            _recompute_one_multiply_by(frm, row);
            frm.refresh_field("custom_operations");
            _render_per_operation_cards(frm);
            frm.dirty();
            d.hide();
        },
    });

    // Item Code → fetch Item.stock_uom into Standard UOM. Dialog fields
    // don't honour the docfield-level `fetch_from`; do it explicitly.
    if (d.fields_dict.item_code) {
        d.fields_dict.item_code.df.onchange = () => {
            const code = d.get_value("item_code");
            if (!code) return;
            frappe.db.get_value("Item", code, "stock_uom").then(r => {
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
