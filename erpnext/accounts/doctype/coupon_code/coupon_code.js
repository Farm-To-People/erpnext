// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Coupon Code', {
	setup: function(frm) {

		frm.disable_autoname_check = true;  // Datahenge: See change to "frappe/frappe/public/js/frappe/form/controls/data.js"

		frm.set_query("pricing_rule", function() {
			return {
				filters: [
					["Pricing Rule","coupon_code_based", "=", "1"]
				]
			};
		});
	},
	refresh: function(frm) {
		// Datahenge: No longer possible, because 1 Coupon Code has many Pricing Rules.
		/*
		if (frm.doc.pricing_rule) {
			frm.add_custom_button(__("Add/Edit Coupon Conditions"), function(){
				frappe.set_route("Form", "Pricing Rule", frm.doc.pricing_rule);
			});
		}
		*/

		// Begin FTP:  Add an anchor link to Coupon Code Usage
		frm.add_custom_button(__("Coupon Usage"), function() {
			frappe.set_route("Form", "Coupon Code Usage", {"coupon_code": frm.doc.name});
		}, __( ))
		//.addClass("btn-warning").css({'color':'black','font-weight': 'regular'});
		// End: FTP
		
		frm.add_custom_button(__("Referral Log"), function() {
			frappe.set_route("List", "Customer Referral Log", {"referred_by": frm.doc.customer});
		}, __( ))		
	}

});
