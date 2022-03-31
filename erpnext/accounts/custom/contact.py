import frappe
from frappe.contacts.doctype.contact.contact import Contact as ContactType

# override, triggered via row in hooks.py

class ERPNextContact(ContactType):

	def on_update(self):
		"""
		After Contact is updated, update the related 'mobile_no' on Customer.
		"""
		if hasattr(super, 'on_update'):
			super.on_update()

		related_customers = get_customers_by_contact_key(self.name)
		for customer_key in related_customers:
			frappe.db.set_value("Customer", customer_key, 'mobile_no', self.mobile_no)
			frappe.db.commit()


def get_customers_by_contact_key(contact_key):
	filters = {
		'parenttype': 'Contact',
		'parentfield': 'links',
		'parent': contact_key,
		'link_doctype': 'Customer'
	}
	customer_keys = frappe.get_list("Dynamic Link", filters=filters, pluck='link_name')
	return customer_keys
