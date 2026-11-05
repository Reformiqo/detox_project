// Revenue WBS Allocations on Blanket Order / Sales Order / Delivery Note / Sales Invoice.
// Revenue-only pickers limited to the document's project and company, Sub WBS follows WBS,
// Category defaults from the WBS, and Allocated Amount stays in sync with the Net Total
// (excluding taxes): single row = net total; multiple rows re-scale proportionally.
// Server side: overrides/revenue_wbs.py.

// Loaded by all four forms; bind the handlers only on the first load.
if (!window.rev_wbs_allocation_bound) {
window.rev_wbs_allocation_bound = true;

['Blanket Order', 'Sales Order', 'Delivery Note', 'Sales Invoice'].forEach(function (doctype) {
    frappe.ui.form.on(doctype, {
        setup(frm) {
            // set_query throws if the site doesn't have this table.
            if (!frm.fields_dict.custom_wbs_allocations) return;
            frm.set_query('wbs_element', 'custom_wbs_allocations', () => {
                const filters = { custom_category_type: 'Revenue', status: ['!=', 'Cancelled'] };
                const project = rev_wbs_project(frm);
                if (project) filters.project = project;
                if (frm.doc.company) filters.company = frm.doc.company;
                return { filters: filters };
            });
            frm.set_query('category', 'custom_wbs_allocations', () => ({ filters: { custom_category_type: 'Revenue', enabled: 1 } }));
            frm.set_query('sub_wbs_element', 'custom_wbs_allocations', (doc, cdt, cdn) => {
                const row = locals[cdt][cdn];
                const filters = { status: ['!=', 'Cancelled'] };
                if (row && row.wbs_element) filters.main_wbs_element = row.wbs_element;
                return { filters: filters };
            });
            if (doctype !== 'Delivery Note' && frappe.meta.has_field(doctype + ' Item', 'custom_wbs_element')) {
                frm.set_query('custom_wbs_element', 'items', () => {
                    const filters = { custom_category_type: 'Revenue', status: ['!=', 'Cancelled'] };
                    const project = rev_wbs_project(frm);
                    if (project) filters.project = project;
                    if (frm.doc.company) filters.company = frm.doc.company;
                    return { filters: filters };
                });
                frm.set_query('custom_sub_wbs_element', 'items', (doc, cdt, cdn) => {
                    const row = locals[cdt][cdn];
                    const filters = { status: ['!=', 'Cancelled'] };
                    if (row && row.custom_wbs_element) filters.main_wbs_element = row.custom_wbs_element;
                    return { filters: filters };
                });
            }
        },
        custom_wbs_allocations_add(frm) { rev_sync_alloc_amounts(frm); },
        validate(frm) { rev_sync_alloc_amounts(frm); },
        items_add(frm) { rev_sync_alloc_delayed(frm); },
        items_remove(frm) { rev_sync_alloc_delayed(frm); }
    });

    frappe.ui.form.on(doctype + ' Item', {
        qty(frm) { rev_sync_alloc_delayed(frm); },
        rate(frm) { rev_sync_alloc_delayed(frm); },
        amount(frm) { rev_sync_alloc_delayed(frm); },
        item_code(frm) { rev_sync_alloc_delayed(frm); }
    });
});

frappe.ui.form.on('Revenue WBS Allocation', {
    wbs_element(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (row && row.sub_wbs_element) {
            frappe.model.set_value(cdt, cdn, 'sub_wbs_element', null);
        }
        if (row && row.wbs_element && !row.category) {
            frappe.db.get_value('WBS Element', row.wbs_element, 'category').then(r => {
                const cat = r && r.message && r.message.category;
                if (cat) frappe.model.set_value(cdt, cdn, 'category', cat);
            });
        }
        rev_sync_alloc_amounts(frm);
    }
});
}

function rev_wbs_project(frm) {
    if (frm.doc.project) return frm.doc.project;
    const it = (frm.doc.items || []).find(r => r.project);
    return it ? it.project : null;
}

function rev_sync_alloc_delayed(frm) {
    setTimeout(function () { rev_sync_alloc_amounts(frm); }, 500);
}

function rev_sync_alloc_amounts(frm) {
    // With WBS on the item rows the server checks the amounts, so don't change them here.
    if (frm.doctype !== 'Delivery Note' && (frm.doc.items || []).some(r => r.custom_wbs_element)) return;
    // Blanket Order keeps its totals in custom fields; all other sales documents use net_total.
    const base = flt(frm.doctype === 'Blanket Order' ? frm.doc.custom_net_total : frm.doc.net_total, 2);
    const rows = frm.doc.custom_wbs_allocations || [];
    if (!rows.length || frm.doc.docstatus !== 0) return;
    if (!base) {
        rows.forEach(r => { if (flt(r.allocated_amount)) frappe.model.set_value(r.doctype, r.name, 'allocated_amount', 0); });
        return;
    }
    if (rows.length === 1) {
        if (flt(rows[0].allocated_amount, 2) !== base) {
            frappe.model.set_value(rows[0].doctype, rows[0].name, 'allocated_amount', base);
        }
        return;
    }
    let sum = 0;
    rows.forEach(r => { sum += flt(r.allocated_amount); });
    if (!sum) {
        frappe.model.set_value(rows[0].doctype, rows[0].name, 'allocated_amount', base);
        return;
    }
    if (flt(sum, 2) === base) return;
    const ratio = base / sum;
    let assigned = 0;
    rows.forEach((r, i) => {
        let val;
        if (i === rows.length - 1) {
            val = flt(base - assigned, 2);
        } else {
            val = flt(flt(r.allocated_amount) * ratio, 2);
            assigned += val;
        }
        frappe.model.set_value(r.doctype, r.name, 'allocated_amount', val);
    });
}
