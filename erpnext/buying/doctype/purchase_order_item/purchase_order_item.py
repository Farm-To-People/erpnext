# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe

from frappe.model.document import Document

# FTP
from ftp.ftp_invent import validate_uom_compatibility
from ftp.ftp_invent.redis.api import try_update_redis_inventory

class PurchaseOrderItem(Document):

	def validate(self, _parent_doc=None):  # pylint: disable=unused-argument
		# Validate there is a conversion between 2 UOMs.
		if not validate_uom_compatibility(self.uom, self.stock_uom, self.item_code):
			raise ValueError(f"There are are no UOM conversion factors between '{self.uom}' and '{self.stock_uom}'.")

	def on_change(self):
		# FTP : This code block will executed using the "Update Items" button on Purchase Orders.
		if self.flags.update_redis:
			try_update_redis_inventory(self.item_code)

def on_doctype_update():
	frappe.db.add_index("Purchase Order Item", ["item_code", "warehouse"])
