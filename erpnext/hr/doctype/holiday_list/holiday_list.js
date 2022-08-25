// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// Datahenge: Despite the suffix "_list", this is NOT JavaScript code for a 'List Page'.
// The ERPNext maintainers just gave this DocType a terrible name: "Holiday List"
// Consequently, this DocType's List Page is actually named 'holiday_list_list.js'
//
// Very confusing.

frappe.ui.form.on('Holiday List', {
	refresh: function(frm) {
		if (frm.doc.holidays) {
			frm.set_value('total_holidays', frm.doc.holidays.length);
		}
	},
	from_date: function(frm) {
		if (frm.doc.from_date && !frm.doc.to_date) {
			var a_year_from_start = frappe.datetime.add_months(frm.doc.from_date, 12);
			frm.set_value("to_date", frappe.datetime.add_days(a_year_from_start, -1));
		}
	}
});
