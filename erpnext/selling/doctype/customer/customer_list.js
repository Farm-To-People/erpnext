frappe.listview_settings["Customer"] = {
	add_fields: ["customer_name", "territory", "customer_group", "customer_type", "image"],

	/*
	Datahenge: This is a workaround, but a useful one.
	By default, the List Page is defaulting the Customer Group based
	on Selling Settings.  So far, I've been unable to debug the code 
	in the core, and resolve why/how this happens.

	I "think" it's using 'bootinfo.sysdefaults.customer_group' or sys_defaults.
	But it's pretty obscure.

	In the meantime, this resolves the Filter issue, but allows the Default Value
	to continue.
	*/

	onload: function(listview) {
		if (!frappe.route_options) { 
			frappe.route_options = {
				"customer_group": ["=", ""],
				"territory": ["=", ""],
			};
		}

		listview.page.add_inner_button(__('Import Shorts/Credits'), import_shorts_credits, __( ));
	},


};


function import_shorts_credits() {

	// Note, later can use 		wrapper: $wrapper

	new frappe.ui.FileUploader({
		// method: 'ftp.utilities.customer_shorts_credits',
		allow_multiple: 0,
		folder: 'Home/Shorts_Credits',
		restrictions: {
			allowed_file_types: [".csv"]
		},		
		on_success: file => {
			frappe.show_alert(__("Processing shorts and credits..."));
			frappe
				.call(
					"ftp.utilities.customer_shorts_credits.upload_shorts_credits_file",
					{
						file_name: file.name
					}
				)
				.then(r => {
					if (r.message) {
						frappe.show_alert(
							__("Unzipped {0} files", [
								r.message
							])
						);
					}
				});
		}
	})
}