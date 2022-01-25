# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe.model.document import Document

class UOM(Document):
	pass


@frappe.whitelist()
def exists_by_name(uom_name):
	result = frappe.db.exists("UOM", uom_name)
	if not result:
		return False	# JavaScript doesn't understand None type.
	return True

@frappe.whitelist()
def create_uom_with_conversions(uom_name, from_uom=None, from_conversion_factor=None, to_uom=None, to_conversion_factor=None):  # pylint: disable=unused-argument
	"""
	This function is called by JS code on the UOM List Page.
	"""
	frappe.msgprint("Unfinished function.")
