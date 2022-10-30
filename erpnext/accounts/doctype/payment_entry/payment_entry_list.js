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

		/*
			Amazing solution for adding a Standard Filter for DocStatus, without creating a pointless, new column named 'status'
			https://discuss.erpnext.com/t/how-to-include-docstatus-in-standard-filter/76382
		*/

		const df = {
			condition: "=",
			default: null,
			fieldname: "docstatus",
			fieldtype: "Select",
			input_class: "input-xs",
			label: "Status",
			is_filter: 1,
			onchange: function() {
				listview.refresh();
			},
			options: [0,1,2],
			placeholder: "Status"
		};
			
		//Add the filter to standard filter section
		let standard_filters_wrapper = listview.page.page_form.find('.standard-filter-section');
		listview.page.add_field(df, standard_filters_wrapper);
		
		//It will be a dropdown with options 1, 2, 3
		//To replace it with Blank space, Draft, Submitted and Cancelled.
		//First selecting the select option, may subject to changes as the the system
		let doc_filter = document.querySelector('select[data-fieldname = "docstatus"]')
		
		//Add first option as blank space
		doc_filter.options.add(new Option(), 0);
		
		//Changing just options' inner html for better user experience
		doc_filter.options[1].innerHTML = 'Draft';
		doc_filter.options[2].innerHTML = 'Submitted';
		doc_filter.options[3].innerHTML = 'Cancelled';
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
				frappe.msgprint("Deposit collection has been added to the Queue; payment entries will be created by background workers.");
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
