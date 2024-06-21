# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

# pylint: disable=invalid-name

# Farm To People modifications
# Disable the ability to Submit PO's.  That's no longer a thing.
'''
SELECT * FROM tabDocPerm
WHERE parent = 'Purchase Order'
AND (submit = 1 OR cancel = 1);

UPDATE
tabDocPerm
SET submit = 0, cancel = 0
WHERE parent = 'Purchase Order'
AND (submit = 1 or cancel = 1);
'''

from __future__ import unicode_literals
from datetime import timedelta

import json
import frappe

from frappe.utils import cstr, flt, cint
from frappe import msgprint, _
from frappe.model.mapper import get_mapped_doc
from erpnext.controllers.buying_controller import BuyingController
from erpnext.stock.doctype.item.item import get_last_purchase_details
from erpnext.stock.stock_balance import update_bin_qty, get_ordered_qty
from frappe.desk.notifications import clear_doctype_notifications
from erpnext.buying.utils import validate_for_items, check_on_hold_or_closed_status
from erpnext.stock.utils import get_bin
from erpnext.accounts.party import get_party_account_currency
from erpnext.stock.doctype.item.item import get_item_defaults
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.accounts.doctype.tax_withholding_category.tax_withholding_category import get_party_tax_withholding_details
from erpnext.accounts.doctype.sales_invoice.sales_invoice import (validate_inter_company_party,
	update_linked_doc, unlink_inter_company_doc)

from erpnext.accounts.custom.address import get_shipping_address
from frappe.contacts.doctype.address.address import get_address_display


from temporal import any_to_date
from ftp.ftp_invent.redis.api import try_update_redis_inventory

form_grid_templates = {
	"items": "templates/form_grid/item_grid.html"
}

class PurchaseOrder(BuyingController):
	def __init__(self, *args, **kwargs):
		super(PurchaseOrder, self).__init__(*args, **kwargs)
		self.status_updater = [{
			'source_dt': 'Purchase Order Item',
			'target_dt': 'Material Request Item',
			'join_field': 'material_request_item',
			'target_field': 'ordered_qty',
			'target_parent_dt': 'Material Request',
			'target_parent_field': 'per_ordered',
			'target_ref_field': 'stock_qty',
			'source_field': 'stock_qty',
			'percent_join_field': 'material_request'
		}]

	def onload(self):
		supplier_tds = frappe.db.get_value("Supplier", self.supplier, "tax_withholding_category")
		self.set_onload("supplier_tds", supplier_tds)

	def before_insert(self):

		# Farm To People: Set the warehouse shipping address on the Purchase Order.
		if not self.shipping_address:
			try:
				address_key = get_shipping_address(self.company)  # returns a tuple, but we need just the 0th component
				if address_key:
					doc_address = frappe.get_doc("Address", address_key[0])
					address_display = get_address_display(doc_address.as_dict())
					self.shipping_address = doc_address.name
					self.shipping_address_display = address_display
			except Exception as ex:
				print(f"Purchase Order before_insert error = {repr(ex)}")
		# Farm To People: Add the default Buying Warehouse.
		if not self.set_warehouse:
			self.set_warehouse = frappe.db.get_single_value("Buying Settings", "default_target_warehouse")

	def before_validate(self):
		# Farm To People:  Ensure that Stock Use Date is related to the Required By Date (schedule_date)
		if self.schedule_date:
			if not self.stock_use_date:
				offset = frappe.db.get_single_value("Buying Settings", "stock_use_days_offset")
				self.stock_use_date = any_to_date(self.schedule_date) + timedelta(days=offset)
		else:
			self.stock_use_date = None

	def validate(self):
		super(PurchaseOrder, self).validate()

		self.set_status()

		# apply tax withholding only if checked and applicable
		self.set_tax_withholding()

		self.validate_supplier()
		self.validate_schedule_date()
		validate_for_items(self)
		self.validate_children(child_docfield_name='items')  # Datahenge: See custom controller on 'document.py'
		self.check_on_hold_or_closed_status()

		self.validate_uom_is_integer("uom", "qty")
		self.validate_uom_is_integer("stock_uom", "stock_qty")

		self.validate_with_previous_doc()
		self.validate_for_subcontracting()
		self.validate_minimum_order_qty()
		self.validate_bom_for_subcontracting_items()
		self.create_raw_materials_supplied("supplied_items")
		self.set_received_qty_for_drop_ship_items()
		validate_inter_company_party(self.doctype, self.supplier, self.company, self.inter_company_order_reference)

	def validate_with_previous_doc(self):
		super(PurchaseOrder, self).validate_with_previous_doc({
			"Supplier Quotation": {
				"ref_dn_field": "supplier_quotation",
				"compare_fields": [["supplier", "="], ["company", "="], ["currency", "="]],
			},
			"Supplier Quotation Item": {
				"ref_dn_field": "supplier_quotation_item",
				"compare_fields": [["project", "="], ["item_code", "="],
					["uom", "="], ["conversion_factor", "="]],
				"is_child_table": True
			},
			"Material Request": {
				"ref_dn_field": "material_request",
				"compare_fields": [["company", "="]],
			},
			"Material Request Item": {
				"ref_dn_field": "material_request_item",
				"compare_fields": [["project", "="], ["item_code", "="]],
				"is_child_table": True
			}
		})


		if cint(frappe.db.get_single_value('Buying Settings', 'maintain_same_rate')):
			self.validate_rate_with_reference_doc([["Supplier Quotation", "supplier_quotation", "supplier_quotation_item"]])

	def set_tax_withholding(self):
		if not self.apply_tds:
			return

		tax_withholding_details = get_party_tax_withholding_details(self, self.tax_withholding_category)

		if not tax_withholding_details:
			return

		accounts = []
		for d in self.taxes:
			if d.account_head == tax_withholding_details.get("account_head"):
				d.update(tax_withholding_details)
			accounts.append(d.account_head)

		if not accounts or tax_withholding_details.get("account_head") not in accounts:
			self.append("taxes", tax_withholding_details)

		to_remove = [d for d in self.taxes
			if not d.tax_amount and d.account_head == tax_withholding_details.get("account_head")]

		for d in to_remove:
			self.remove(d)

		# calculate totals again after applying TDS
		self.calculate_taxes_and_totals()

	def validate_supplier(self):
		prevent_po = frappe.db.get_value("Supplier", self.supplier, 'prevent_pos')
		if prevent_po:
			standing = frappe.db.get_value("Supplier Scorecard", self.supplier, 'status')
			if standing:
				frappe.throw(_("Purchase Orders are not allowed for {0} due to a scorecard standing of {1}.")
					.format(self.supplier, standing))

		warn_po = frappe.db.get_value("Supplier", self.supplier, 'warn_pos')
		if warn_po:
			standing = frappe.db.get_value("Supplier Scorecard",self.supplier, 'status')
			frappe.msgprint(_("{0} currently has a {1} Supplier Scorecard standing, and Purchase Orders to this supplier should be issued with caution.").format(self.supplier, standing), title=_("Caution"), indicator='orange')

		self.party_account_currency = get_party_account_currency("Supplier", self.supplier, self.company)

	def validate_minimum_order_qty(self):
		if not self.get("items"): return
		items = list(set(d.item_code for d in self.get("items")))

		itemwise_min_order_qty = frappe._dict(frappe.db.sql("""select name, min_order_qty
			from tabItem where name in ({0})""".format(", ".join(["%s"] * len(items))), items))

		itemwise_qty = frappe._dict()
		for d in self.get("items"):
			itemwise_qty.setdefault(d.item_code, 0)
			itemwise_qty[d.item_code] += flt(d.stock_qty)

		for item_code, qty in itemwise_qty.items():
			if flt(qty) < flt(itemwise_min_order_qty.get(item_code)):
				frappe.throw(_("Item {0}: Ordered qty {1} cannot be less than minimum order qty {2} (defined in Item).").format(item_code,
					qty, itemwise_min_order_qty.get(item_code)))

	def validate_bom_for_subcontracting_items(self):
		if self.is_subcontracted == "Yes":
			for item in self.items:
				if not item.bom:
					frappe.throw(_("BOM is not specified for subcontracting item {0} at row {1}")
						.format(item.item_code, item.idx))

	def get_schedule_dates(self):
		for d in self.get('items'):
			if d.material_request_item and not d.schedule_date:
				d.schedule_date = frappe.db.get_value("Material Request Item",
						d.material_request_item, "schedule_date")


	@frappe.whitelist()
	def get_last_purchase_rate(self):
		"""get last purchase rates for all items"""

		conversion_rate = flt(self.get('conversion_rate')) or 1.0
		for d in self.get("items"):
			if d.item_code:
				last_purchase_details = get_last_purchase_details(d.item_code, self.name)
				if last_purchase_details:
					d.base_price_list_rate = (last_purchase_details['base_price_list_rate'] *
						(flt(d.conversion_factor) or 1.0))
					d.discount_percentage = last_purchase_details['discount_percentage']
					d.base_rate = last_purchase_details['base_rate'] * (flt(d.conversion_factor) or 1.0)
					d.price_list_rate = d.base_price_list_rate / conversion_rate
					d.rate = d.base_rate / conversion_rate
					d.last_purchase_rate = d.rate
				else:

					item_last_purchase_rate = frappe.get_cached_value("Item", d.item_code, "last_purchase_rate")
					if item_last_purchase_rate:
						d.base_price_list_rate = d.base_rate = d.price_list_rate \
							= d.rate = d.last_purchase_rate = item_last_purchase_rate

	# Check for Closed status
	def check_on_hold_or_closed_status(self):
		check_list =[]
		for d in self.get('items'):
			if d.meta.get_field('material_request') and d.material_request and d.material_request not in check_list:
				check_list.append(d.material_request)
				check_on_hold_or_closed_status('Material Request', d.material_request)

	def update_requested_qty(self):
		material_request_map = {}
		for d in self.get("items"):
			if d.material_request_item:
				material_request_map.setdefault(d.material_request, []).append(d.material_request_item)

		for mr, mr_item_rows in material_request_map.items():
			if mr and mr_item_rows:
				mr_obj = frappe.get_doc("Material Request", mr)

				if mr_obj.status in ["Stopped", "Cancelled"]:
					frappe.throw(_("Material Request {0} is cancelled or stopped").format(mr), frappe.InvalidStatusError)

				mr_obj.update_requested_qty(mr_item_rows)

	def update_ordered_qty(self, po_item_rows=None):
		"""update requested qty (before ordered_qty is updated)"""
		item_wh_list = []
		for d in self.get("items"):
			if (not po_item_rows or d.name in po_item_rows) \
				and [d.item_code, d.warehouse] not in item_wh_list \
				and frappe.get_cached_value("Item", d.item_code, "is_stock_item") \
				and d.warehouse and not d.delivered_by_supplier:
					item_wh_list.append([d.item_code, d.warehouse])
		for item_code, warehouse in item_wh_list:
			update_bin_qty(item_code, warehouse, {
				"ordered_qty": get_ordered_qty(item_code, warehouse)
			})

	def check_modified_date(self):
		mod_db = frappe.db.sql("select modified from `tabPurchase Order` where name = %s",
			self.name)
		date_diff = frappe.db.sql("select '%s' - '%s' " % (mod_db[0][0], cstr(self.modified)))

		if date_diff and date_diff[0][0]:
			msgprint(_("{0} {1} has been modified. Please refresh.").format(self.doctype, self.name),
				raise_exception=True)

	def update_status(self, status):
		self.check_modified_date()
		self.set_status(update=True, status=status)
		self.update_requested_qty()
		self.update_ordered_qty()
		if self.is_subcontracted == "Yes":
			self.update_reserved_qty_for_subcontract()

		self.notify_update()
		clear_doctype_notifications(self)

	def on_submit(self):
		super(PurchaseOrder, self).on_submit()

		if self.is_against_so():
			self.update_status_updater()

		self.update_prevdoc_status()
		self.update_requested_qty()
		self.update_ordered_qty()
		self.validate_budget()

		if self.is_subcontracted == "Yes":
			self.update_reserved_qty_for_subcontract()

		frappe.get_doc('Authorization Control').validate_approving_authority(self.doctype,
			self.company, self.base_grand_total)

		self.update_blanket_order()

		update_linked_doc(self.doctype, self.name, self.inter_company_order_reference)
		for each in self.items:
			try_update_redis_inventory(each.item_code)  # update Redis after Purchase Order is Submitted.


	def on_cancel(self):
		super(PurchaseOrder, self).on_cancel()

		if self.is_against_so():
			self.update_status_updater()

		if self.has_drop_ship_item():
			self.update_delivered_qty_in_sales_order()

		if self.is_subcontracted == "Yes":
			self.update_reserved_qty_for_subcontract()

		self.check_on_hold_or_closed_status()

		frappe.db.set(self,'status','Cancelled')

		self.update_prevdoc_status()

		# Must be called after updating ordered qty in Material Request
		# bin uses Material Request Items to recalculate & update
		self.update_requested_qty()
		self.update_ordered_qty()

		self.update_blanket_order()

		unlink_inter_company_doc(self.doctype, self.name, self.inter_company_order_reference)

		for each in self.items:
			try_update_redis_inventory(each.item_code)  # update Redis after Purchase Order has been cancelled.

	def on_update(self):
		"""
		Farm To People:  After the PO is updated, refresh the Redis Inventory Quantities.
		"""
		def method1():
			# Option 1:  Update every PO line indiscriminately.
			item_codes = [d.item_code for d in self.get("items")]

			doc_orig = self.get_doc_before_save()
			if doc_orig:
				item_codes_before = [d.item_code for d in doc_orig.get("items")]
				item_codes = item_codes + item_codes_before

			item_codes = list(set(item_codes))  # de-duplicate
			if not item_codes:
				return

			for item_code in item_codes:
				is_sales_item = frappe.db.get_value("Item", item_code, "is_sales_item")
				if is_sales_item:
					try_update_redis_inventory(item_code)

		def method2():  # pylint: disable=unused-variable
			# Option 2: Try to detect changes (stock_qty, new_line, delivery_date, FTP parms)
			for idx, purchase_line in enumerate(self.items):
				line_orig = self.get_doc_before_save().get("items")[idx]
				if line_orig.stock_qty != purchase_line.stock_qty:
					print(f"(2 Change Detected: PO Line stock quantity) : {line_orig.stock_qty} {line_orig.stock_uom} --> {purchase_line.stock_qty}")
					try_update_redis_inventory(purchase_line.item_code)

		# Brian: For now just update whenever the PO is touched.  Otherwise, so many data-modification scenarios we'd have to detect.
		method1()

	def update_status_updater(self):
		self.status_updater.append({
			'source_dt': 'Purchase Order Item',
			'target_dt': 'Sales Order Item',
			'target_field': 'ordered_qty',
			'target_parent_dt': 'Sales Order',
			'target_parent_field': '',
			'join_field': 'sales_order_item',
			'target_ref_field': 'stock_qty',
			'source_field': 'stock_qty'
		})

	def update_delivered_qty_in_sales_order(self):
		"""Update delivered qty in Sales Order for drop ship"""
		sales_orders_to_update = []
		for item in self.items:
			if item.sales_order and item.delivered_by_supplier == 1:
				if item.sales_order not in sales_orders_to_update:
					sales_orders_to_update.append(item.sales_order)

		for so_name in sales_orders_to_update:
			so = frappe.get_doc("Sales Order", so_name)
			so.update_delivery_status()
			so.set_status(update=True)
			so.notify_update()

	def has_drop_ship_item(self):
		return any(d.delivered_by_supplier for d in self.items)

	def is_against_so(self):
		return any(d.sales_order for d in self.items if d.sales_order)

	def set_received_qty_for_drop_ship_items(self):
		for item in self.items:
			if item.delivered_by_supplier == 1:
				item.received_qty = item.qty

	def update_reserved_qty_for_subcontract(self):
		for d in self.supplied_items:
			if d.rm_item_code:
				stock_bin = get_bin(d.rm_item_code, d.reserve_warehouse)
				stock_bin.update_reserved_qty_for_sub_contracting()

	def update_receiving_percentage(self):
		total_qty, received_qty = 0.0, 0.0
		for item in self.items:
			received_qty += item.received_qty
			total_qty += item.qty
		if total_qty:
			self.db_set("per_received", flt(received_qty/total_qty) * 100, update_modified=False)
		else:
			self.db_set("per_received", 0, update_modified=False)


	def after_delete(self):
		"""
		After deleting a Purchase Order, try to update Redis.
		"""
		item_codes = [d.item_code for d in self.get("items")]
		doc_orig = self.get_doc_before_save()
		if doc_orig:
			item_codes_before = [d.item_code for d in doc_orig.get("items")]
			item_codes = item_codes + item_codes_before

		item_codes = list(set(item_codes))  # de-duplicate
		if not item_codes:
			return

		for item_code in item_codes:
			try_update_redis_inventory(item_code)


	@frappe.whitelist()
	def revert_to_draft_ftp(self):
		"""
		Change a Purchase Order from 'Submitted' to 'Draft'.
		"""
		# This function is called via JavaScript on 'purchase_order.js'
		if self.status != "To Receive and Bill":
			frappe.throw(_("Purchase Order can only be reset to 'Draft' when status is 'To Receive and Bill'"))
		frappe.db.set_value("Purchase Order", self.name, "docstatus", 0)
		frappe.db.set_value(self.doctype, self.name, "status", "Draft")
		frappe.db.sql("""UPDATE `tabPurchase Order Item` SET docstatus = 0 WHERE parent = %s""", self.name)  # child Order Lines
		self.reload()


# ----------------------------------------
# 			END CONTROLLER METHODS
# ----------------------------------------


def item_last_purchase_rate(name, conversion_rate, item_code, conversion_factor= 1.0):
	"""get last purchase rate for an item"""

	conversion_rate = flt(conversion_rate) or 1.0

	last_purchase_details =  get_last_purchase_details(item_code, name)
	if last_purchase_details:
		last_purchase_rate = (last_purchase_details['base_net_rate'] * (flt(conversion_factor) or 1.0)) / conversion_rate
		return last_purchase_rate
	else:
		item_last_purchase_rate = frappe.get_cached_value("Item", item_code, "last_purchase_rate")
		if item_last_purchase_rate:
			return item_last_purchase_rate

@frappe.whitelist()
def close_or_unclose_purchase_orders(names, status):
	if not frappe.has_permission("Purchase Order", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	names = json.loads(names)
	for name in names:
		po = frappe.get_doc("Purchase Order", name)
		if po.docstatus == 1:
			if status == "Closed":
				if po.status not in ( "Cancelled", "Closed") and (po.per_received < 100 or po.per_billed < 100):
					po.update_status(status)
			else:
				if po.status == "Closed":
					po.update_status("Draft")
			po.update_blanket_order()

	frappe.local.message_log = []  # pylint: disable=assigning-non-slot

def set_missing_values(source, target):
	target.ignore_pricing_rule = 1
	target.run_method("set_missing_values")
	target.run_method("calculate_taxes_and_totals")

@frappe.whitelist()
def make_purchase_receipt(source_name, target_doc=None):
	def update_item(obj, target, source_parent):
		target.qty = flt(obj.qty) - flt(obj.received_qty)
		target.stock_qty = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.conversion_factor)
		target.amount = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.rate)
		target.base_amount = (flt(obj.qty) - flt(obj.received_qty)) * \
			flt(obj.rate) * flt(source_parent.conversion_rate)

	doc = get_mapped_doc("Purchase Order", source_name,	{
		"Purchase Order": {
			"doctype": "Purchase Receipt",
			"field_map": {
				"supplier_warehouse":"supplier_warehouse"
			},
			"validation": {
				"docstatus": ["=", 1],
			}
		},
		"Purchase Order Item": {
			"doctype": "Purchase Receipt Item",
			"field_map": {
				"name": "purchase_order_item",
				"parent": "purchase_order",
				"bom": "bom",
				"material_request": "material_request",
				"material_request_item": "material_request_item"
			},
			"postprocess": update_item,
			"condition": lambda doc: abs(doc.received_qty) < abs(doc.qty) and doc.delivered_by_supplier!=1
		},
		"Purchase Taxes and Charges": {
			"doctype": "Purchase Taxes and Charges",
			"add_if_empty": True
		}
	}, target_doc, set_missing_values)

	return doc

@frappe.whitelist()
def make_purchase_invoice(source_name, target_doc=None):
	return get_mapped_purchase_invoice(source_name, target_doc)

@frappe.whitelist()
def make_purchase_invoice_from_portal(purchase_order_name):
	doc = get_mapped_purchase_invoice(purchase_order_name, ignore_permissions=True)
	if doc.contact_email != frappe.session.user:
		frappe.throw(_('Not Permitted'), frappe.PermissionError)
	doc.save()
	frappe.db.commit()
	frappe.response['type'] = 'redirect'
	frappe.response.location = '/purchase-invoices/' + doc.name

def get_mapped_purchase_invoice(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		target.flags.ignore_permissions = ignore_permissions
		set_missing_values(source, target)
		#Get the advance paid Journal Entries in Purchase Invoice Advance

		if target.get("allocate_advances_automatically"):
			target.set_advances()

	def update_item(obj, target, source_parent):
		target.amount = flt(obj.amount) - flt(obj.billed_amt)
		target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = target.amount / flt(obj.rate) if (flt(obj.rate) and flt(obj.billed_amt)) else flt(obj.qty)

		item = get_item_defaults(target.item_code, source_parent.company)
		item_group = get_item_group_defaults(target.item_code, source_parent.company)
		target.cost_center = (obj.cost_center
			or frappe.db.get_value("Project", obj.project, "cost_center")
			or item.get("buying_cost_center")
			or item_group.get("buying_cost_center"))

	fields = {
		"Purchase Order": {
			"doctype": "Purchase Invoice",
			"field_map": {
				"party_account_currency": "party_account_currency",
				"supplier_warehouse":"supplier_warehouse"
			},
			"validation": {
				"docstatus": ["=", 1],
			}
		},
		"Purchase Order Item": {
			"doctype": "Purchase Invoice Item",
			"field_map": {
				"name": "po_detail",
				"parent": "purchase_order",
			},
			"postprocess": update_item,
			"condition": lambda doc: (doc.base_amount==0 or abs(doc.billed_amt) < abs(doc.amount))
		},
		"Purchase Taxes and Charges": {
			"doctype": "Purchase Taxes and Charges",
			"add_if_empty": True
		},
	}

	if frappe.get_single("Accounts Settings").automatically_fetch_payment_terms == 1:
		fields["Payment Schedule"] = {
			"doctype": "Payment Schedule",
			"add_if_empty": True
		}

	doc = get_mapped_doc("Purchase Order", source_name,	fields,
		target_doc, postprocess, ignore_permissions=ignore_permissions)

	return doc

@frappe.whitelist()
def make_rm_stock_entry(purchase_order, rm_items):
	rm_items_list = rm_items

	if isinstance(rm_items, str):
		rm_items_list = json.loads(rm_items)
	elif not rm_items:
		frappe.throw(_("No Items available for transfer"))

	if rm_items_list:
		fg_items = list(set(d["item_code"] for d in rm_items_list))
	else:
		frappe.throw(_("No Items selected for transfer"))

	if purchase_order:
		purchase_order = frappe.get_doc("Purchase Order", purchase_order)

	if fg_items:
		items = tuple(set(d["rm_item_code"] for d in rm_items_list))
		item_wh = get_item_details(items)

		stock_entry = frappe.new_doc("Stock Entry")
		stock_entry.purpose = "Send to Subcontractor"
		stock_entry.purchase_order = purchase_order.name
		stock_entry.supplier = purchase_order.supplier
		stock_entry.supplier_name = purchase_order.supplier_name
		stock_entry.supplier_address = purchase_order.supplier_address
		stock_entry.address_display = purchase_order.address_display
		stock_entry.company = purchase_order.company
		stock_entry.to_warehouse = purchase_order.supplier_warehouse
		stock_entry.set_stock_entry_type()

		for item_code in fg_items:
			for rm_item_data in rm_items_list:
				if rm_item_data["item_code"] == item_code:
					rm_item_code = rm_item_data["rm_item_code"]
					items_dict = {
						rm_item_code: {
							"po_detail": rm_item_data.get("name"),
							"item_name": rm_item_data["item_name"],
							"description": item_wh.get(rm_item_code, {}).get('description', ""),
							'qty': rm_item_data["qty"],
							'from_warehouse': rm_item_data["warehouse"],
							'stock_uom': rm_item_data["stock_uom"],
							'serial_no': rm_item_data.get('serial_no'),
							'batch_no': rm_item_data.get('batch_no'),
							'main_item_code': rm_item_data["item_code"],
							'allow_alternative_item': item_wh.get(rm_item_code, {}).get('allow_alternative_item')
						}
					}
					stock_entry.add_to_stock_entry_detail(items_dict)
		return stock_entry.as_dict()
	else:
		frappe.throw(_("No Items selected for transfer"))
	return purchase_order.name

def get_item_details(items):
	item_details = {}
	for d in frappe.db.sql("""select item_code, description, allow_alternative_item from `tabItem`
		where name in ({0})""".format(", ".join(["%s"] * len(items))), items, as_dict=1):
		item_details[d.item_code] = d

	return item_details

def get_list_context(context=None):
	from erpnext.controllers.website_list_for_contact import get_list_context
	list_context = get_list_context(context)
	list_context.update({
		'show_sidebar': True,
		'show_search': True,
		'no_breadcrumbs': True,
		'title': _('Purchase Orders'),
	})
	return list_context

@frappe.whitelist()
def update_status(status, name):
	po = frappe.get_doc("Purchase Order", name)
	po.update_status(status)
	po.update_delivered_qty_in_sales_order()

@frappe.whitelist()
def make_inter_company_sales_order(source_name, target_doc=None):
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_inter_company_transaction
	return make_inter_company_transaction("Purchase Order", source_name, target_doc)

@frappe.whitelist()
def get_materials_from_supplier(purchase_order, po_details):
	"""
	DH: This vanilla ERPNext function is used as part of raw material subcontracting with a Supplier.
	"""
	if isinstance(po_details, str):
		po_details = json.loads(po_details)

	doc = frappe.get_cached_doc('Purchase Order', purchase_order)
	doc.initialized_fields()
	doc.purchase_orders = [doc.name]
	doc.get_available_materials()

	if not doc.available_materials:
		frappe.throw(_('Materials are already received against the purchase order {0}')
			.format(purchase_order))

	return make_return_stock_entry_for_subcontract(doc.available_materials, doc, po_details)

def make_return_stock_entry_for_subcontract(available_materials, po_doc, po_details):
	ste_doc = frappe.new_doc('Stock Entry')
	ste_doc.purpose = 'Material Transfer'
	ste_doc.purchase_order = po_doc.name
	ste_doc.company = po_doc.company
	ste_doc.is_return = 1

	for key, value in available_materials.items():
		if not value.qty:
			continue

		if value.batch_no:
			for batch_no, qty in value.batch_no.items():
				if qty > 0:
					add_items_in_ste(ste_doc, value, value.qty, po_details, batch_no)
		else:
			add_items_in_ste(ste_doc, value, value.qty, po_details)

	ste_doc.set_stock_entry_type()
	ste_doc.calculate_rate_and_amount()

	return ste_doc

def add_items_in_ste(ste_doc, row, qty, po_details, batch_no=None):
	item = ste_doc.append('items', row.item_details)

	po_detail = list(set(row.po_details).intersection(po_details))
	item.update({
		'qty': qty,
		'batch_no': batch_no,
		'basic_rate': row.item_details['rate'],
		'po_detail': po_detail[0] if po_detail else '',
		's_warehouse': row.item_details['t_warehouse'],
		't_warehouse': row.item_details['s_warehouse'],
		'item_code': row.item_details['rm_item_code'],
		'subcontracted_item': row.item_details['main_item_code'],
		'serial_no': '\n'.join(row.serial_no) if row.serial_no else ''
	})

# Farm To People:

@frappe.whitelist()
def get_suppliers_default_items(supplier_id):
	"""
	Used by JavaScript when adding lines to a Purchase Order.
	One line for every Item's default supplier.
	"""
	from erpnext.stock.get_item_details import get_conversion_factor, get_price_list_rate_for

	filters = { "parenttype": "Item", "default_supplier": supplier_id }
	results = frappe.get_all("Item Default", filters=filters, fields=["parent"])
	item_names = [ result['parent'] for result in results]

	result = []
	for item_code in item_names:
		item_data = frappe.db.get_values('Item', filters={"name": item_code}, fieldname=["purchase_uom", "item_name"], as_dict=True)
		if item_data:
			item_data = item_data[0]
		else:
			print(f"WARNING: No data found for Item = '{item_code}'")
			continue
		item_data['item_code'] = item_code

		# If there is a purchase UOM, try to calculate the Conversion Factor.
		if item_data['purchase_uom']:
			conversion_factor = get_conversion_factor(item_code=item_code, uom=item_data['purchase_uom'])['conversion_factor']
			item_data['conversion_factor'] = conversion_factor

		price_list_rate = get_price_list_rate_for(args={
			"supplier": supplier_id,
			"price_list": "Standard Buying",
			"item_code": item_code,
			"qty": 1,
			"uom": item_data['purchase_uom'],
			"transaction_date": frappe.utils.getdate()
		}, item_code=item_code)

		item_data['price_list_rate'] = price_list_rate

		result.append(item_data)

	return result


@frappe.whitelist()
def get_purchase_lines_based_on_sales(supplier_id, delivery_date_from, delivery_date_to):
	"""
	Given a date range, find all Daily Orders, aggregate by Item Code, and return a List of Dictionary.
	"""

	price_list_name = frappe.db.get_single_value("Buying Settings", "buying_price_list")

	query = """
		SELECT
			 OrderLine.item_code					AS item_code
			,tabItem.item_name
			,tabItem.stock_uom						AS uom
			,IFNULL(ItemPrice.price_list_rate,0)	AS price_list_rate		
			,SUM(OrderLine.qty_stock_unit)			AS quantity

		FROM 	
			`tabDaily Order Item`	AS OrderLine

		INNER JOIN
			tabItem
		ON
			tabItem.name = OrderLine.item_code
		AND tabItem.is_purchase_item = 1

		INNER JOIN
			`tabDaily Order`	AS OrderHeader
		ON
			OrderHeader.name = OrderLine.parent
		AND OrderHeader.status_delivery not in ('Cancelled', 'Anonymous', 'Paused', 'Skipped')

		INNER JOIN
			`tabItem Default`	AS ItemDefaults
		ON
			ItemDefaults.parent = tabItem.item_code
		AND ItemDefaults.default_supplier = %(default_supplier_id)s
		AND ItemDefaults.company = 'Farm To People'

		LEFT JOIN
			`tabItem Price`	AS ItemPrice
		ON
			ItemPrice.buying = 1
		AND ItemPrice.item_code = tabItem.item_code 
		AND ItemPrice.uom  = tabItem.stock_uom
		AND (ItemPrice.valid_from is NULL	OR ItemPrice.valid_from <=  DATE(CONVERT_TZ( UTC_TIMESTAMP(), 'UTC', 'EST')) )
		AND (ItemPrice.valid_upto is NULL	or ItemPrice.valid_upto >=  DATE(CONVERT_TZ( UTC_TIMESTAMP(), 'UTC', 'EST')) )
		AND ItemPrice.price_list = %(price_list_name)s

		WHERE
			OrderLine.delivery_date >= %(date_from)s
		AND OrderLine.delivery_date <= %(date_to)s

		GROUP BY
			 OrderLine.item_code
			,tabItem.item_name
			,tabItem.stock_uom	
	"""

	result = frappe.db.sql(query, values={"default_supplier_id": supplier_id,
	                                      "date_from": delivery_date_from,
	                                      "date_to": delivery_date_to,
										  "price_list_name": price_list_name }, as_dict=True)

	return result  # returns the List of Dictionary to JavaScript caller.
