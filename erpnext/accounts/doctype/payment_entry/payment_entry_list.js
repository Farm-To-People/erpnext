frappe.listview_settings["Payment Entry"] = {
	onload: function (listview) {
		if (listview.page.fields_dict.party_type) {
			listview.page.fields_dict.party_type.get_query = function () {
				return {
					filters: {
						name: ["in", Object.keys(frappe.boot.party_account_types)],
					},
				};
			};
		}
		console.log("payment_entry_list.js: I'm still being called, and that is a good thing.");
	},
};
