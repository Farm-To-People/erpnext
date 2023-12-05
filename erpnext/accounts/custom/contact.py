import frappe
from frappe.contacts.doctype.contact.contact import Contact as ContactType

# override, triggered via row in hooks.py

class ERPNextContact(ContactType):

	def on_update(self):
		"""
		After Contact is updated, update the related 'mobile_no' on Customer.
		"""
		if hasattr(super, 'on_update'):
			super().on_update()

		related_customers = get_customers_by_contact_key(self.name)
		for customer_key in related_customers:
			frappe.db.set_value("Customer", customer_key, 'mobile_no', self.mobile_no)

		# Also cascade into Daily Orders:
		self.update_daily_orders(verbose=False)

	def update_daily_orders(self, verbose=False):
		# NOTE: This works nicely inside the ERPNext module, because we don't need to import FTP objects.
		from datetime import timedelta
		from temporal import date_to_iso_string
		from temporal.core import get_system_date

		# Find the Customer(s) associated with this Contact record.
		customer_keys = [ link.link_name for link in self.links if link.link_doctype == "Customer"]
		if not customer_keys:
			return

		orders_touched = False
		tomorrow_date = get_system_date() + timedelta(days=1)
		tomorrow_date = date_to_iso_string(tomorrow_date)

		for customer_key in customer_keys:
			# For each customer found, update the Orders.
			filters = { "delivery_date": [">=", tomorrow_date],
			            "customer": customer_key,
						"is_past_cutoff": False }  # Bug fix February 22nd, 2023, from Slack conversation and customer Gleap.

			daily_orders = frappe.get_list("Daily Order", filters=filters, pluck='name')
			for each_key in daily_orders:
				if verbose:
					print(f"Customer updated Contact, so cascading into Daily Order {each_key}")
				doc_daily_order = frappe.get_doc("Daily Order", each_key)
				doc_daily_order.contact_phone = self.mobile_no
				doc_daily_order.db_update()
				orders_touched = True

		if orders_touched:
			frappe.msgprint("\u2713 Updated contact phone on Daily Orders.")

	# <- Datahenge Additions


def get_customers_by_contact_key(contact_key):
	filters = {
		'parenttype': 'Contact',
		'parentfield': 'links',
		'parent': contact_key,
		'link_doctype': 'Customer'
	}
	customer_keys = frappe.get_list("Dynamic Link", filters=filters, pluck='link_name')
	return customer_keys
