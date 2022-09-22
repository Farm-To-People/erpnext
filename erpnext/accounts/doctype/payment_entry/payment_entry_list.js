frappe.listview_settings['Payment Entry'] = {

	onload: function(listview) {
		if (listview.page.fields_dict.party_type) {
			listview.page.fields_dict.party_type.get_query = function() {
				return {
					"filters": {
						"name": ["in", Object.keys(frappe.boot.party_account_types)],
					}
				};
			};
		}

		// Farm To People: add a button for Collect Deposits
		listview.page.add_inner_button(__("Collect Deposits"), function () {
			collect_deposits(listview);
		});		
		

	}
};

function collect_deposits(listview) {

	var mydialog = new frappe.ui.Dialog({
		title: 'Collect Deposits',
		width: 100,
		fields: [
			{
				'fieldtype': 'Text',
				'default': "Collect deposits from turkeys and hams",
				'read_only': true
			},
			{
				'fieldtype': 'Date',
				'label': __('From Delivery Date'),
				'fieldname': 'from_delivery_date',
				'default': frappe.datetime.nowdate(),				
			},
			{
				'fieldtype': 'Date',
				'label': __('To Delivery Date'),
				'fieldname': 'to_delivery_date',
				'default': frappe.datetime.nowdate(),				
			},
		]
	});

	mydialog.set_primary_action(__('Create'), args => {
		let foo = frappe.call({
			method: 'ftp.ftp_module.doctype.farm_box.farm_box.create_demo_farmbox',
			// Reminder: Argument names must match those in the Python function declaration.
			args: { dlv_period_name: args.dlv_period_name,
				    item_code:       args.item_code},
			callback: function(r) {
				console.log("Callback 1: Created a new Farm Box document.");
				if (r.message) {
					console.log("Callback 2: Created a new Farm Box document.");
					// Brian: Have to refresh in the callback.  Otherwise will get called early!
					listview.refresh();  // This refreshes the List, but does -not- Reload each Doc :/
				}
			}
		});
		mydialog.hide();  // After callback, close dialog regardless of result.
	});

	// Ask Python for the current Delivery Period, then run the dialog.
	frappe.call({
		method: "ftp.ftp_module.doctype.delivery_period.delivery_period.get_current_period_name",
		args: null,
		callback: (r) => {
			if (r.message) {
				mydialog.set_values({'dlv_period_current': r.message});  // just for user reference
				mydialog.show();
			}
		},
	});
	// end

};
