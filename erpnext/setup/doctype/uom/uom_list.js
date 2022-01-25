frappe.listview_settings['UOM'] = {

	onload: function (listview) {

		// Add a button above the List View filters.
		listview.page.add_inner_button(__("Create with Conversions (FTP)"), function () {
			create_uom_with_conversions(listview);
		});			
	}
};

function create_uom_with_conversions(listview) {

	var mydialog = new frappe.ui.Dialog({
		title: 'Create a new Unit of Measure (UOM)',
		width: 100,
		fields: [
			{
				'fieldname': 'uom_name',
				'fieldtype': 'Data',
				'label': __('New UOM'),
				reqd: 1
			},
			{
				'fieldtype': 'Link',
				'label': __('From UOM'),
				'fieldname': 'from_uom',
			},
			{
				'fieldtype': 'Float',
				'label': __('Conversion Factor'),
				'fieldname': 'from_conversion_factor',
			},
			{
				'fieldtype': 'Link',
				'label': __('To UOM'),
				'fieldname': 'to_uom',
				'default': 'Each'
			},
			{
				'fieldtype': 'Float',
				'label': __('Conversion Factor'),
				'fieldname': 'to_conversion_factor',
			},
		]
	});

	/*
		df.onchange		Any edit of characters in real-time
	*/

	/*	
	mydialog.fields_dict["uom_name"].df.onchange_modified = () => {
		// Value of 'UOM Name' was changed.  Verify it does not already exist in UOM table.
		let cell_value = mydialog.fields_dict.uom_name.input.value;
		frappe.call ({
			method: 'erpnext.setup.doctype.uom.uom.exists_by_name',
			args: {uom_name: cell_value},	// Python named argument 'uom_name'
			callback: function(r) {
				console.log(r.message);
				if ( r.message == true ) {
					frappe.throw(__('UOM already exists.'));
				}
			},
//			freeze: true,
//			freeze_message: 'UOM already exists.'
		});
	}
	*/

	mydialog.set_primary_action(__('Create UOM'), args => {
		frappe.call({
			method: 'erpnext.setup.doctype.uom.uom.create_uom_with_conversions',
			// Reminder: Argument names must match those in the Python function declaration.
			args: {
				uom_name:	args.uom_name, 
				from_uom:	args.from_uom, 
				from_conversion_factor: args.from_conversion_factor,
				to_uom: args.to_uom,
				to_conversion_factor: args.to_conversion_factor
			},
			callback: function(r) {
				console.log("Callback 1: Created a new Unit of Measure.");
				if (r.message) {
					console.log("Callback 2: Created a new Unit of Measure.");
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
