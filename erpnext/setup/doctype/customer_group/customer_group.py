# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe import _


from frappe.utils.nestedset import NestedSet, get_root_of
class CustomerGroup(NestedSet):
	nsm_parent_field = 'parent_customer_group'
	def validate(self):
		if not self.parent_customer_group:
			self.parent_customer_group = get_root_of("Customer Group")
		# FTP Custom Code - Ensure that Onfleet Merchants actually exis
		if self.onfleet_merchant and bool(frappe.db.get_single_value("Onfleet Configuration", "enable_onfleet_integration")):
			from ftp.ftp_fleet.onfleet_api.organization_merchant import build_merchant_name_id_map  # Late import due to custom App dependency
			merchant_map = build_merchant_name_id_map()
			if not merchant_map.get(self.onfleet_merchant):
				message = f"Onfleet API cannot find Merchant named = '{self.onfleet_merchant}'"
				available_options = '<br>'.join(merchant_map.keys())
				message += f"<br><br>Available options are:<br>{available_options}"
				raise ValueError(message)

	def on_update(self):
		self.validate_name_with_customer()
		super(CustomerGroup, self).on_update()
		self.validate_one_root()

		self.update_order_shipping_rules()	# FTP: update all Customer Orders associated with this Customer Group.

	def validate_name_with_customer(self):
		if frappe.db.exists("Customer", self.name):
			frappe.msgprint(_("A customer with the same name already exists"), raise_exception=1)

	def update_order_shipping_rules(self):
		"""
		Useful when the Customer Group's default Shipping Rule is modified, to update all existing Orders.
		"""
		if not self.has_value_changed('default_shipping_rule'):
			return

		customer_names = frappe.get_list("Customer", filters={"customer_group": self.name}, pluck='name')

		# TODO: This could be a potentially lengthy update?
		for customer_name in customer_names:
			filters = { "status_delivery": ["in", ["Ready", "Good Faith", "Skipped", "Paused"]],
						"customer": customer_name,
						"is_past_cutoff": False,
						"status_editing": "Unlocked" }

			order_names = frappe.get_list("Daily Order", filters=filters, pluck='name')
			for order_name in order_names:
				doc_order = frappe.get_doc("Daily Order", order_name)
				doc_order.set_shipping_rule()
				doc_order.save()


def get_parent_customer_groups(customer_group):
	lft, rgt = frappe.db.get_value("Customer Group", customer_group, ['lft', 'rgt'])

	return frappe.db.sql("""select name from `tabCustomer Group`
		where lft <= %s and rgt >= %s
		order by lft asc""", (lft, rgt), as_dict=True)

def on_doctype_update():
	frappe.db.add_index("Customer Group", ["lft", "rgt"])
