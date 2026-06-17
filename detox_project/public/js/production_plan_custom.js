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
    operation_name(frm) {
        _refresh_operation_options(frm);
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
    operation_name(frm) {
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

// Phase 7 — populate the Detox Production Plan Operation grid's
// operation_name autocomplete with the Operations defined in the
// custom_processes table. Free-text fallback stays allowed so the
// user can still hand-type an operation name.
function _refresh_operation_options(frm) {
    const grid = frm.fields_dict.custom_operations && frm.fields_dict.custom_operations.grid;
    if (!grid) return;
    const ops = (frm.doc.custom_processes || [])
        .map(p => (p.operation_name || "").trim())
        .filter(Boolean);
    const docfield = grid.docfields && grid.docfields.find(d => d.fieldname === "operation_name");
    if (docfield) {
        // operation_name is a Data field on the child JSON; expose the
        // process names via autocompletions so the user can pick from them.
        docfield.autocomplete = ops;
    }
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
