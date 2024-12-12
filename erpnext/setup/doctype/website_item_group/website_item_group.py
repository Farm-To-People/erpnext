# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WebsiteItemGroup(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		item_group: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	pass


def on_doctype_update():
	# Farm To People: Do not allow the same Item Group to be assigned twice (bug in standard code)
	frappe.db.add_index("Website Item Group", ["parent", "parenttype", "item_group"])
	frappe.db.add_unique("Website Item Group", ["parent", "parenttype", "item_group"])
