// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Holiday List', {
	refresh: function(frm) {
		if (frm.doc.holidays) {
			frm.set_value('total_holidays', frm.doc.holidays.length);
		}

		if (frm.doc.holidays) {
			frm.events.add_button_shift_orders(frm);
		}

	},
	from_date: function(frm) {
		if (frm.doc.from_date && !frm.doc.to_date) {
			var a_year_from_start = frappe.datetime.add_months(frm.doc.from_date, 12);
			frm.set_value("to_date", frappe.datetime.add_days(a_year_from_start, -1));
		}
	},
	add_button_shift_orders: function (frm) {
		frm.add_custom_button(__('Shift Orders on Holiday'), () => {

			frappe.confirm(__("Confirm shifting order Delivery Dates?"),
				function(){
					frappe.call({
						type:"GET",
						doc: frm.doc,
						method:"shift_daily_orders",
						}).done(() => {
							frm.reload_doc();
						}).fail(() => {
							console.log("Error while shifting Orders to new dates.")					
						})
				},
				function(){
					window.close();
				}			
			); // end frappe.confirm
		});
	} //end add_button_shift_orders

});
