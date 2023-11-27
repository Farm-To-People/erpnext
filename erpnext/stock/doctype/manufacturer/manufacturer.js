// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Manufacturer', {
	refresh: function(frm) {
		frappe.dynamic_link = { doc: frm.doc, fieldname: 'name', doctype: 'Manufacturer' };
		if (frm.doc.__islocal) {
			hide_field(['address_html','contact_html']);
			frappe.contacts.clear_address_and_contact(frm);
		}
		else {
			unhide_field(['address_html','contact_html']);
			frappe.contacts.render_address_and_contact(frm);
		};

		frm.events.add_button_show_sanity_record(frm);
	},

	// This function adds a button "Show Sanity Data"
	add_button_show_sanity_record: function (frm) {

		frm.add_custom_button(__('Show Sanity Data'), () => {
			frappe.call(
				{
					doc: frm.doc,
					method: 'get_sanity_record',  // ERPNext Document class method.
					callback: function(r) {
						if (r.message) {
							let sanity_data_string = JSON.stringify(r.message, null, 2);  // Convert dictionary object to String.
							frappe.msgprint(`<br>${sanity_data_string}`);
						}
						else {
							frappe.msgprint("No response returned from Python function 'get_sanity_record()'");
						}
					}
				}).done(() => {

				}).fail(() => {
					console.log("Error attempting to retrieve data from Sanity.")
				});
		});
	},

});
