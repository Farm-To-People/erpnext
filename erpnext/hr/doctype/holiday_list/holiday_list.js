// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// Datahenge: Despite the suffix "_list", this is NOT JavaScript code for a 'List Page'.
// The ERPNext maintainers just gave this DocType a terrible name: "Holiday List"
// Consequently, this DocType's List Page is actually named 'holiday_list_list.js'
// Very confusing.

frappe.ui.form.on('Holiday List', {
	refresh: function(frm) {
		if (frm.doc.holidays) {
			frm.set_value('total_holidays', frm.doc.holidays.length);
		}

		// FTP:  First custom button.
		if (frm.doc.holidays) {
			frm.events.add_button_shift_orders(frm);
		}

		// FTP:  Second custom button.
		frm.add_custom_button(__('Shift Orders by Delivery Zone'), () => {
			shift_orders_by_delivery_zone(frm);
		})
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

function shift_orders_by_delivery_zone(frm) {

	// Datahenge:  Frappe doesn't allow Dialogs to focus automatically on Calendar Dates.  Weird.
	//             So the Borough needs to the first dialog entry, otherwise it doesn't feel right.
	var my_dialog = new frappe.ui.Dialog({
		title: 'Shift Orders by Delivery Zone',
		width: 100,
		fields: [
			{
				'fieldtype': 'Link',
				'label': __('Delivery Zone'),
				'fieldname': 'delivery_zone',
				'options': 'Delivery Zone',
				'mandatory': true,
			},
			{
				'fieldtype': 'Date',
				'label': __('Current Delivery Date'),
				'fieldname': 'current_delivery_date',
				'mandatory': true,
				'set_focus': true
			},
			{
				'fieldtype': 'Date',
				'label': __('New Delivery Date'),
				'fieldname': 'new_delivery_date',
				'mandatory': true,
			}
		]
	});

	my_dialog.set_primary_action(__('Change Order Dates'), () => {
		let dialog_args = my_dialog.get_values();
		my_dialog.hide();  // after callback, close dialog regardless of result.
		frappe.call({
			doc: frm.doc,
			method: 'shift_orders_by_delivery_zone',
			args: dialog_args
		}).done( (r) => {
			if (r.message) {
				console.log("Queued updates to Orders...");
				console.log(r.message);
			}
		}).fail( (r) => {
			if (r.message) {
				console.log("Failure Message:");
				console.log(r.message);
			}
		}).then( () => {
			frm.reload_doc();
		});

	});
	my_dialog.show();  	// Now that dialog is defined, run it.
}
