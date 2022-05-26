// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Item Price", {
	onload: function (frm) {
		// Fetch price list details
		frm.add_fetch("price_list", "buying", "buying");
		frm.add_fetch("price_list", "selling", "selling");
		frm.add_fetch("price_list", "currency", "currency");

		// Fetch item details
		frm.add_fetch("item_code", "item_name", "item_name");
		frm.add_fetch("item_code", "description", "item_description");
		frm.add_fetch("item_code", "stock_uom", "uom");

		frm.set_df_property("bulk_import_help", "options",
			'<a href="/app/data-import-tool/Item Price">' + __("Import in Bulk") + '</a>');

		frm.set_query('batch_no', function() {
			return {
				filters: {
					'item': frm.doc.item_code
				}
			};
		});
	}

	,after_save: function(frm) {

		frappe.db.get_single_value("FTP Custom Settings", "open_dialog_on_price_change").then(val => {
			if (val == false) {
				return;
			}

			var my_dialog = new frappe.ui.Dialog({
				title: 'Update Orders?',
				width: 100,
				fields: [
					{
						fieldtype: 'Select',
						fieldname: 'update_existing_orders',
						label: __('Update existing orders?'),
						options: __('No\nYes'),
						default: 'No',
						reqd: 1,
						onchange: function() {
							if(my_dialog.fields_dict.update_existing_orders.value == 'Yes') {
								my_dialog.set_df_property("delivery_date_start", "hidden", 0);
							} else {
								my_dialog.set_df_property("delivery_date_start", "hidden", 1);
							}
						}
					},
					{
						'fieldtype': 'Date',
						'fieldname': 'delivery_date_start',
						'label': __('Starting with Delivery Date:'),
						default: frm.doc.valid_from,
						hidden: true
					}
				]
			});

			my_dialog.set_primary_action(__('Continue'), args => {

				if (args.update_existing_orders == 'Yes') {

					const dialog_data = my_dialog.get_values();
					let item_code = frm.doc.item_code;
					let delivery_date_start = dialog_data.delivery_date_start;

					frappe.call({
						method:"ftp.utilities.pricing.js_recalculate_order_prices",
						args: {
							"item_code": item_code,
							"delivery_date_start": delivery_date_start
						},
						callback: function(r) {
							if (r.message) {
								frappe.msgprint(r.message);
							}
						}
					});
				}
				my_dialog.hide();	
			});
			my_dialog.show();
		});
	}
});
