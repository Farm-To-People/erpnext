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
			/*
			{
				fieldname: "intro",
				fieldtype: "HTML",
				options: '<h3>'
					+ __("Collect deposits from Orders")
				+ '</h3>'
			},
			*/
			{
				'fieldtype': 'Date',
				'label': __('From Delivery Date'),
				'fieldname': 'from_delivery_date',
				//'default': frappe.datetime.nowdate(),
				'default': "2022-11-20",
			},
			{
				'fieldtype': 'Date',
				'label': __('To Delivery Date'),
				'fieldname': 'to_delivery_date',
				// 'default': frappe.datetime.nowdate(),
				'default': "2022-11-23",
			},
			{
				'fieldtype': 'Check',
				'label': __('Pre-Order items only'),
				'fieldname': 'only_pre_order_items',
				'default': 1,				
			},
			{
				fieldname: "help",
				fieldtype: "HTML",
				options: '<br><p>'
					+ __("NOTE: One payment entry will be created, per Order.")
				+ '</p>'
			}
		]
	});

	mydialog.set_primary_action(__('Create'), args => {
		let foo = frappe.call({
			method: 'ftp.ftp_receivables.deposits.collect_deposits',
			// Reminder: Argument names must match those in the Python function declaration.
			args: { from_delivery_date: args.from_delivery_date,
				    to_delivery_date:   args.to_delivery_date,
					only_pre_order_items: args.only_pre_order_items
			},
			callback: function(r) {
				console.log("Callback 1: Finished call to collect_deposits()");
				if (r.message) {
					console.log(`Callback 2: Message returned was ${r}`);
					listview.refresh();  // This refreshes the List, but does -not- Reload each Doc :/
				}
			}
		});
		mydialog.hide();  // After callback, close dialog regardless of result.
	});

	mydialog.show();

};  // end of function collect_deposits()
