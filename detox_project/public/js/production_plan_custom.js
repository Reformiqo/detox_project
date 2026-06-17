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
        _refresh_operation_options(frm);
    },

    refresh(frm) {
        _apply_no_bom_visibility(frm);
        _recompute_multiply_by(frm);
        _refresh_operation_options(frm);
        _render_operations_breakdown(frm);
    },

    custom_no_bom(frm) {
        _apply_no_bom_visibility(frm);
    },
});

frappe.ui.form.on("Detox Production Plan Process", {
    operation_name(frm, cdt, cdn) {
        _refresh_operation_options(frm);
        // Phase 7c — auto-add a matching row in Operations & Materials
        // for this Operation. One Materials row per Operation
        // (uniqueness enforced).
        _autosync_process_to_materials(frm, locals[cdt][cdn]);
        _render_operations_breakdown(frm);
    },
    workstation(frm) {
        _render_operations_breakdown(frm);
    },
    custom_processes_remove(frm) {
        _refresh_operation_options(frm);
        _render_operations_breakdown(frm);
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
    operation_name(frm, cdt, cdn) {
        // Phase 7c — Operation is unique per Materials row. If the
        // user just picked an Operation that already exists on
        // another row, clear it and tell them.
        _enforce_materials_operation_uniqueness(frm, locals[cdt][cdn]);
        _render_operations_breakdown(frm);
    },
    item_code(frm) {
        _render_operations_breakdown(frm);
    },
    item_type(frm) {
        _render_operations_breakdown(frm);
    },
    custom_operations_remove(frm) {
        _render_operations_breakdown(frm);
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
    ["custom_fg_items", "custom_processes", "custom_operations",
     "custom_operations_view"].forEach(fn => {
        if (frm.fields_dict[fn]) frm.toggle_display(fn, on);
    });
}

// Phase 7b — operation_name on both Process + Operation child tables
// is now a Link → Operation (ERPNext manufacturing master). Restrict
// the materials grid's Link picker to the Operations already defined
// in this plan's custom_processes table, so a Materials row can only
// reference an Operation that's been declared.
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

// Phase 7 — read-only HTML breakdown showing materials grouped per
// Operation (matches Sahil's screenshot — one mini-table per Operation
// row defined in custom_processes).
function _render_operations_breakdown(frm) {
    const wrap = frm.fields_dict.custom_operations_view && frm.fields_dict.custom_operations_view.$wrapper;
    if (!wrap) return;
    const processes = (frm.doc.custom_processes || []);
    const ops = (frm.doc.custom_operations || []);
    if (!processes.length && !ops.length) {
        wrap.find(".phase7-breakdown").remove();
        return;
    }

    const escape = (s) => frappe.utils.escape_html(String(s == null ? "" : s));
    const byOp = new Map();
    processes.forEach(p => {
        if (!p.operation_name) return;
        byOp.set(p.operation_name, {workstation: p.workstation || "", rows: []});
    });
    // Bucket the materials under their operation name; collect orphans
    // (rows whose operation_name doesn't match any Process row).
    const orphans = [];
    ops.forEach(o => {
        const key = (o.operation_name || "").trim();
        if (key && byOp.has(key)) byOp.get(key).rows.push(o);
        else orphans.push(o);
    });

    const tableHeader = `<thead><tr>
        <th>Item Code</th><th>Item Type</th>
        <th>Std UOM</th><th>Manual UOM</th>
        <th class='text-right'>Std Rate</th>
        <th class='text-right'>Qty per Unit</th>
        <th class='text-right'>Multiply By</th>
        <th>Subcontracted</th>
        <th>Cost Center</th><th>Project</th>
    </tr></thead>`;
    const rowHTML = (r) => `<tr>
        <td>${escape(r.item_code)}</td>
        <td>${escape(r.item_type)}</td>
        <td>${escape(r.standard_uom)}</td>
        <td>${escape(r.manual_uom)}</td>
        <td class='text-right'>${escape(r.standard_rate)}</td>
        <td class='text-right'>${escape(r.qty_per_unit)}</td>
        <td class='text-right'>${escape(r.multiply_by)}</td>
        <td>${r.is_subcontracted ? "Yes" : "No"}</td>
        <td>${escape(r.cost_center)}</td>
        <td>${escape(r.project)}</td>
    </tr>`;

    let html = "<div class='phase7-breakdown' style='margin-top:10px'>";
    byOp.forEach((bucket, opName) => {
        html += `<div style='margin:14px 0 6px 0'>
            <span style='font-weight:600;font-size:14px'>${escape(opName)}</span>
            <span class='text-muted' style='margin-left:8px;font-size:12px'>
                Workstation: ${escape(bucket.workstation) || "<em>—</em>"}
            </span>
        </div>
        <table class='table table-bordered' style='font-size:12px;margin-bottom:6px'>
            ${tableHeader}
            <tbody>${bucket.rows.length ? bucket.rows.map(rowHTML).join("") :
                "<tr><td colspan='10' class='text-muted text-center'>No materials linked to this Operation yet.</td></tr>"}</tbody>
        </table>`;
    });
    if (orphans.length) {
        html += `<div style='margin:14px 0 6px 0;color:#dc3545;font-weight:600'>
            Unassigned (no matching Process row)
        </div>
        <table class='table table-bordered' style='font-size:12px'>
            ${tableHeader}<tbody>${orphans.map(rowHTML).join("")}</tbody>
        </table>`;
    }
    html += "</div>";

    wrap.find(".phase7-breakdown").remove();
    wrap.append(html);
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

// Phase 7c — when a Process row gets an Operation, mirror it into a
// fresh row in Operations & Materials so the user doesn't have to add
// it twice. Skip if a Materials row already references the same
// Operation (uniqueness rule).
function _autosync_process_to_materials(frm, proc_row) {
    if (!proc_row || !proc_row.operation_name) return;
    const op = proc_row.operation_name;
    const already = (frm.doc.custom_operations || []).some(
        r => r.operation_name === op
    );
    if (already) return;
    const new_row = frappe.model.add_child(frm.doc, "Detox Production Plan Operation", "custom_operations");
    new_row.operation_name = op;
    // Carry CC + Project down from the header to save a trip; user can override.
    if (frm.doc.custom_cost_center && !new_row.cost_center) {
        new_row.cost_center = frm.doc.custom_cost_center;
    }
    if (frm.doc.project && !new_row.project) {
        new_row.project = frm.doc.project;
    }
    frm.refresh_field("custom_operations");
    frappe.show_alert({
        message: __("Auto-added Operations & Materials row for {0}.", [op]),
        indicator: "blue",
    });
}

// Phase 7c — Operation is unique in the Materials table. If a row's
// operation_name already exists on another row, clear it.
function _enforce_materials_operation_uniqueness(frm, row) {
    if (!row || !row.operation_name) return;
    const op = row.operation_name;
    const dupes = (frm.doc.custom_operations || []).filter(
        r => r.operation_name === op && r.name !== row.name
    );
    if (dupes.length === 0) return;
    frappe.model.set_value(row.doctype, row.name, "operation_name", "");
    frappe.msgprint({
        title: __("Operation already used"),
        message: __(
            "Operation '{0}' is already on another Operations & Materials row. " +
            "Each Operation may appear only once here.", [op]
        ),
        indicator: "orange",
    });
}
