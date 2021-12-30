""" pricing_rule.py """
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors

# For license information, please see license.txt

from __future__ import unicode_literals
import copy
import json
import re
from six import string_types

import frappe
from frappe import throw, _
from frappe.utils import flt, cint, getdate
from frappe.model.document import Document

# pylint: disable=protected-access

# ---- Datahenge ----
DEBUG_MODE = False

def dprint(msg):
	if DEBUG_MODE:
		print(msg)
# -------------------

apply_on_dict = {"Item Code": "items",
	"Item Group": "item_groups", "Brand": "brands"}

other_fields = ["other_item_code", "other_item_group", "other_brand"]

class PricingRule(Document):
	def validate(self):
		self.validate_mandatory()
		self.validate_duplicate_apply_on()
		self.validate_applicable_for_selling_or_buying()
		self.validate_min_max_amt()
		self.validate_min_max_qty()
		self.cleanup_fields_value()
		self.validate_rate_or_discount()
		self.validate_max_discount()
		self.validate_price_list_with_currency()
		self.validate_dates()
		self.validate_condition()
		self.validate_nth()  # Farm To People

		if not self.margin_type: self.margin_rate_or_amount = 0.0

	def validate_duplicate_apply_on(self):
		field = apply_on_dict.get(self.apply_on)
		values = [d.get(frappe.scrub(self.apply_on)) for d in self.get(field) if field]
		if len(values) != len(set(values)):
			frappe.throw(_("Duplicate {0} found in the table").format(self.apply_on))

	def validate_mandatory(self):
		for apply_on, field in apply_on_dict.items():
			if self.apply_on == apply_on and len(self.get(field) or []) < 1:
				throw(_("{0} is not added in the table").format(apply_on), frappe.MandatoryError)

		tocheck = frappe.scrub(self.get("applicable_for", ""))
		if tocheck and not self.get(tocheck):
			throw(_("{0} is required").format(self.meta.get_label(tocheck)), frappe.MandatoryError)

		if self.apply_rule_on_other:
			o_field = 'other_' + frappe.scrub(self.apply_rule_on_other)
			if not self.get(o_field) and o_field in other_fields:
				frappe.throw(_("For the 'Apply Rule On Other' condition the field {0} is mandatory")
					.format(frappe.bold(self.apply_rule_on_other)))


		if self.price_or_product_discount == 'Price' and not self.rate_or_discount:
			throw(_("Rate or Discount is required for the price discount."), frappe.MandatoryError)

		if self.apply_discount_on_rate:
			if not self.priority:
				throw(_("As the field {0} is enabled, the field {1} is mandatory.")
					.format(frappe.bold("Apply Discount on Discounted Rate"), frappe.bold("Priority")))

			if self.priority and cint(self.priority) == 1:
				throw(_("As the field {0} is enabled, the value of the field {1} should be more than 1.")
					.format(frappe.bold("Apply Discount on Discounted Rate"), frappe.bold("Priority")))

	def validate_applicable_for_selling_or_buying(self):
		if not self.selling and not self.buying:
			throw(_("Atleast one of the Selling or Buying must be selected"))

		if not self.selling and self.applicable_for in ["Customer", "Customer Group",
				"Territory", "Sales Partner", "Campaign"]:
			throw(_("Selling must be checked, if Applicable For is selected as {0}")
				.format(self.applicable_for))

		if not self.buying and self.applicable_for in ["Supplier", "Supplier Group"]:
			throw(_("Buying must be checked, if Applicable For is selected as {0}")
				.format(self.applicable_for))

	def validate_min_max_qty(self):
		if self.min_qty and self.max_qty and flt(self.min_qty) > flt(self.max_qty):
			throw(_("Min Qty can not be greater than Max Qty"))

	def validate_min_max_amt(self):
		if self.min_amt and self.max_amt and flt(self.min_amt) > flt(self.max_amt):
			throw(_("Min Amt can not be greater than Max Amt"))

	def cleanup_fields_value(self):
		for logic_field in ["apply_on", "applicable_for", "rate_or_discount"]:
			fieldname = frappe.scrub(self.get(logic_field) or "")

			# reset all values except for the logic field
			options = (self.meta.get_options(logic_field) or "").split("\n")
			for f in options:
				if not f: continue

				scrubbed_f = frappe.scrub(f)

				if logic_field == 'apply_on':
					apply_on_f = apply_on_dict.get(f, f)
				else:
					apply_on_f = scrubbed_f

				if scrubbed_f != fieldname:
					self.set(apply_on_f, None)

		if self.mixed_conditions and self.get("same_item"):
			self.same_item = 0

		apply_rule_on_other = frappe.scrub(self.apply_rule_on_other or "")

		cleanup_other_fields = (other_fields if not apply_rule_on_other
			else [o_field for o_field in other_fields if o_field != 'other_' + apply_rule_on_other])

		for other_field in cleanup_other_fields:
			self.set(other_field, None)

	def validate_rate_or_discount(self):
		for field in ["Rate"]:
			if flt(self.get(frappe.scrub(field))) < 0:
				throw(_("{0} can not be negative").format(field))

		if self.price_or_product_discount == 'Product' and not self.free_item:
			if self.mixed_conditions:
				frappe.throw(_("Free item code is not selected"))
			else:
				self.same_item = 1

	def validate_max_discount(self):
		if self.rate_or_discount == "Discount Percentage" and self.get("items"):
			for d in self.items:
				max_discount = frappe.get_cached_value("Item", d.item_code, "max_discount")
				if max_discount and flt(self.discount_percentage) > flt(max_discount):
					throw(_("Max discount allowed for item: {0} is {1}%").format(d.item_code, max_discount))

	def validate_price_list_with_currency(self):
		if self.currency and self.for_price_list:
			price_list_currency = frappe.db.get_value("Price List", self.for_price_list, "currency", True)
			if not self.currency == price_list_currency:
				throw(_("Currency should be same as Price List Currency: {0}").format(price_list_currency))

	def validate_dates(self):
		if self.is_cumulative and not (self.valid_from and self.valid_upto):
			frappe.throw(_("Valid from and valid upto fields are mandatory for the cumulative"))

		if self.valid_from and self.valid_upto and getdate(self.valid_from) > getdate(self.valid_upto):
			frappe.throw(_("Valid from date must be less than valid upto date"))

	def validate_condition(self):
		if self.condition and ("=" in self.condition) and re.match(r"""[\w\.:_]+\s*={1}\s*[\w\.@'"]+""", self.condition):
			frappe.throw(_("Invalid condition expression"))

	def validate_nth(self):
		"""
		Farm To People validation.
		"""
		if (self.nth_order_only) and (self.first_n_orders):
			frappe.throw(_("Can only choose one of 'Apply to N-th Order Only' 'First N Orders'"))

		if (self.nth_order_only) and (self.first_n_orders) and (self.nth_order_only > self.first_n_orders):
			frappe.throw(_("Value of Nth Order Only cannot exceed value of First N Orders."))

#--------------------------------------------------------------------------------

@frappe.whitelist()
def apply_pricing_rule(args, doc=None):
	"""
		Arguments:
			args:	String
			doc:	String

		Example of args:

		args = {
			"items": [{"doctype": "", "name": "", "item_code": "", "brand": "", "item_group": ""}, ...],
			"customer": "something",
			"customer_group": "something",
			"territory": "something",
			"supplier": "something",
			"supplier_group": "something",
			"currency": "something",
			"conversion_rate": "something",
			"price_list": "something",
			"plc_conversion_rate": "something",
			"company": "something",
			"transaction_date": "something",
			"campaign": "something",
			"sales_partner": "something",
			"ignore_pricing_rule": "something",
			"doctype": "something",
			"coupon_codes":  "something"
		}
	"""

	# ---------------
	# Datahenge:	This function is called directly by JS code on the ERPNext website.
	#
	# There are 2 callers that matter the most to me:
	#
	#	1. erpnext/public/js/controllers/transaction.js  (via changing Company, Qty)
	#	2. daily_order.js
	#
	#	I need 'args' to provide a new piece of information:  Coupon Code Set.
	#	To accomplish this, I should modify the JS code, and add Coupon Code Set to it's payload.
	# ---------------

	# Convert 'args' from JSON string to Python Dictionary.
	if isinstance(args, string_types):
		args = json.loads(args)

	args = frappe._dict(args)

	if not args.transaction_type:
		set_transaction_type(args)

	# list of dictionaries
	out = []

	if args.get("doctype") == "Material Request": return out

	# Extract the "items" into their own variable.
	# Sales Order Item, Daily Order Item, etc.
	item_list = args.get("items")
	args.pop("items")  # DH: could have just done this on line above

	set_serial_nos_based_on_fifo = frappe.db.get_single_value("Stock Settings",
		"automatically_set_serial_nos_based_on_fifo")

	for item in item_list:
		args_copy = copy.deepcopy(args)
		# Next, merge the Order Line dictionary (item) into the 'args' dictionary
		args_copy.update(item)
		# Datahenge Requirements:  The 'args_copy' must contain the Coupon Code Set as a List of String.
		# Also, removed an unused argument below:
		data = get_pricing_rule_for_item(args_copy, doc=doc)
		out.append(data)
		if not item.get("serial_no") and set_serial_nos_based_on_fifo and not args.get('is_return'):
			out[0].update(get_serial_no_for_item(args_copy))

	return out

def get_serial_no_for_item(args):
	from erpnext.stock.get_item_details import get_serial_no

	item_details = frappe._dict({
		"doctype": args.doctype,
		"name": args.name,
		"serial_no": args.serial_no
	})
	if args.get("parenttype") in ("Sales Invoice", "Delivery Note") and flt(args.stock_qty) > 0:
		item_details.serial_no = get_serial_no(args)
	return item_details

def get_pricing_rule_for_item(args, doc=None, for_validate=False):  # pylint: disable=too-many-branches,too-many-statements
	#
	# Datahenge:	A more-accurate function name would be 'get_pricing_rules_for_order_lines()'
	#  				This function is EXTREMELY IMPORTANT.
	#
	"""
	Arguments:
		args: A Python Dictionary.
		doc:  A parent DocType such as Sales Order, Daily Order, Purchase Order.

	Returns:
		New dictionary 'item_details'
	"""

	from erpnext.accounts.doctype.pricing_rule.utils import (get_pricing_rules,
			get_applied_pricing_rules, get_pricing_rule_items, get_product_discount_rule)

	# pylint: disable=pointless-string-statement
	"""
	Datahenge Notes:

	Argument 'args' (a dictionary) should have a key 'coupon_codes', which is a List of Strings.

	There are two(2) different process flows, and ways of arriving here:

	1. JAVASCRIPT PATH
		* 'apply_pricing_rule'
		* erpnext/accounts/doctype/pricing_rule/pricing_rule.py, Line: 213
		* Same Module as this comment; just scroll up a bit.
		* Argument 'doc' is a JSON string.

	2. PYTHON SERVERSIDE PATH:
    	* 'get_item_details'
    	* erpnext/erpnext/stock/get_item_details.py, Line: 121
		* Argument 'doc' is a Frappe Class.
		* Quite a lot of 'get_item_details' is building the 'args', prior to arriving here.

	A huge challenge/problem with this function is Inconsistent Argument Types.  What is args?

	When called from a Sales Order:
	  * 'args' is a Dictionary of Sales Order, Sales Order Item, Coupon Codes, Price Lists.
	  * 'doc' is the SalesOrder document.
	"""

	# ----------------
	# 1. Validate and modify function arguments.
	# ----------------
	from temporal import validate_datatype  # Late import from across Python modules.

	# args
	validate_datatype('args', args, dict, mandatory=True)
	args = frappe._dict(args)  # pylint: disable=protected-access

	# doc
	if doc and isinstance(doc, string_types):  # argument 'doc' is a string (assumption is that it's a JSON string)
		doc = json.loads(doc)  # convert JSON string to a Python Dictionary.
	if doc:  # Convert 'doc' to a Frappe Dictionary
		doc = frappe.get_doc(doc)

	if doc and doc.doctype in ['Daily Order', 'Sales Order'] and 'coupon_codes' not in args.keys():
		frappe.throw("Argument 'args' is missing an expected key: 'coupon_codes'")

	# DH: The metadata key 'istable' is one of the more-ridiculous naming conventions in Frappe Framework.
	#     Because -every- Document is a table.  What they actually meant was 'is_child_table'
	#    :eyeroll:
	if doc and bool(frappe.get_doc('DocType', doc.doctype).istable):
		frappe.throw("Invalid call to 'get_pricing_rule_for_item()'.  Cannot pass a Child Document.")

	# ----------------
	# 2. Debugging output
	# ----------------

	dprint("\n*****************PRICING RULE.py*************************")
	# frappe.print_caller()
	# dprint("1. Function Arguments")
	# dprint(f"\targs : a Dictionary with {len(args.keys())} keys.")
	# dprint(f"\tdoc : a Document of type {type(doc)}")

	# ----------------
	# 3. Datahenge: Try to extract the Coupon Codes, and write to 'args' as a List of String.
	# ----------------
	if doc and doc.doctype in ['Sales Order', 'Daily Order'] and \
		(('coupon_codes' not in args) or (not args['coupon_codes'])):

		if hasattr(doc, 'coupon_code_set'):
			args['coupon_codes'] = []
			for coupon_code_doc in doc.coupon_code_set:
				args.coupon_codes.append(coupon_code_doc.coupon_code)

	# ----------------
	# standard code
	# ----------------

	if (args.get('is_free_item') or
		args.get("parenttype") == "Material Request"): return {}

	item_details = frappe._dict({
		"doctype": args.doctype,
		"has_margin": False,
		"name": args.name,
		"free_item_data": [],  # not sure why this is here.
		"parent": args.parent,
		"parenttype": args.parenttype,
		"child_docname": args.get('child_docname')
	})

	# 4. Early exit condition: If 'ignore_pricing_rule', disable all Pricing Rules,
	#                       then return the price information for all Lines.
	if args.ignore_pricing_rule or not args.item_code:
		dprint(f"* Automatic Pricing is disabled for Order Line {doc.name}")
		if frappe.db.exists(args.doctype, args.name) and args.get("pricing_rules"):
			item_details = remove_pricing_rule_for_item(args.get("pricing_rules"),
				item_details, args.get('item_code'))
		return item_details

	update_args_for_pricing_rule(args)

	# DH: Confusing way of writing this, but leaving it alone for now:
	pricing_rules = (get_applied_pricing_rules(args.get('pricing_rules'))
		if for_validate and args.get("pricing_rules") else get_pricing_rules(args, doc))
	validate_datatype("pricing_rules", pricing_rules, list)

	dprint(f"\nThere are {len(pricing_rules)} Potential Pricing Rules.\n")
	# If there are no Potential Pricing Rules, but the 'args' mentions some?  Remove those rules from the Order.
	if not pricing_rules and args.get("pricing_rules"):
		dprint("Arguments contain 'pricing_rules' that must be removed from the Order.")
		item_details = remove_pricing_rule_for_item(args.get("pricing_rules"),
			                                        item_details,
													args.get('item_code'))
		return item_details

	applied_rules = []  # originally named 'rules' in standard code.

	for pricing_rule in pricing_rules:

		# For each --potential-- Pricing Rule, determine if it's actually applicable or not.
		if not pricing_rule:
			frappe.throw("Unexpected Condition: No pricing rules found while looping.")
			# continue

		if isinstance(pricing_rule, str):
			dprint(f"Evaluating Pricing Rule '{pricing_rule}' ...")
		elif isinstance(pricing_rule, dict):
			dprint(f"Evaluating Pricing Rule '{pricing_rule['name']}' ...")
		else:
			frappe.throw(f"Unexpected type '{type(pricing_rule)}' for variable 'pricing_rule'")

		# This variable's type may be String (name of a Pricing Rule) or Dictionary (values of a Pricing Rule)
		if isinstance(pricing_rule, string_types):
			pricing_rule = frappe.get_cached_doc("Pricing Rule", pricing_rule)
			pricing_rule.apply_rule_on_other_items = get_pricing_rule_items(pricing_rule)

		# Skip if it's only a suggestion? (no idea how that works)
		if pricing_rule.get('suggestion'):
			print("Skipping Pricing Rule, because it's only a suggestion?")
			continue

		# ------------------------------------
		# Farm To People: Nth Order
		# ------------------------------------
		if doc and doc.doctype == 'Daily Order' and bool(pricing_rule.nth_order_only):
			dprint(f"* Pricing Rule {pricing_rule['name']} requires an Nth order condition.")

			# Create a list of all non-cancelled Daily Orders
			nth_order_list = create_nth_order_list(customer_id=doc.customer,
													daily_order=doc)

			#order_position = next((index for (index, d) in enumerate(nth_order_list)
			#                       if d["name"] == doc_daily_order.name), None) + 1
			# print(f"* Relative position of Daily Order '{doc_daily_order.name}' = {order_position}")

			# Case 1:  Fewer orders exist than the Nth Order.
			if len(nth_order_list) < pricing_rule.nth_order_only:
				dprint(f"* Skipping Pricing rule {pricing_rule['name']} because Order {doc.name} is not the {pricing_rule.nth_order_only}th order")
				continue
			# Case 2:  Is this the Nth?
			elif nth_order_list[pricing_rule.nth_order_only - 1]['name'] != doc.name:
				dprint(f"* Skipping Pricing rule {pricing_rule['name']} because Order {doc.name} is not the {pricing_rule.nth_order_only}th order")
				continue  # Skip This Pricing Rule, because this Order is not the Nth Order.
			else:
				print(f"* Applying an Nth Order pricing rule to Daily Order {doc.name}")
		# ------------------------------------

		# ------------------------------------
		# Farm To People: Pricing Rule based on Order Line's Origin Code.
		# ------------------------------------
		if (pricing_rule.limit_to_origin != "All") and (doc.doctype == 'Daily Order Item'):
			if pricing_rule.limit_to_origin == 'ALC' and doc.origin_code != 'A la carte':
				continue
			if pricing_rule.limit_to_origin == 'Subscription' and doc.origin_code != 'Subscription':
				continue
		# ------------------------------------

		item_details.validate_applied_rule = pricing_rule.get("validate_applied_rule", 0)
		item_details.price_or_product_discount = pricing_rule.get("price_or_product_discount")

		applied_rules.append(get_pricing_rule_details(args, pricing_rule))

		if pricing_rule.mixed_conditions or pricing_rule.apply_rule_on_other:
			item_details.update({
				'apply_rule_on_other_items': json.dumps(pricing_rule.apply_rule_on_other_items),
				'price_or_product_discount': pricing_rule.price_or_product_discount,
				'apply_rule_on': (frappe.scrub(pricing_rule.apply_rule_on_other)
					if pricing_rule.apply_rule_on_other else frappe.scrub(pricing_rule.get('apply_on')))
			})

		# ------------------------------------
		# Farm To People: Pricing Rule based on Coupon Codes.
		#
		# Standard code never accomplished this.  Coupon Codes, if they worked at all, only worked with ERPNext Website stuff.
		# ------------------------------------
		if not pricing_rule_matches_coupon_list(pricing_rule, args.coupon_codes):
			# But what if a rule already exists on the Order.  And now then Coupon is deleted?
			# Well, then delete the Rule.  Otherwise, INFINITE LOOP (yes...seriously)
			dprint(f"Removing Pricing Rule '{pricing_rule['name']}' from order, because of missing Coupon Code.")
			item_details = remove_pricing_rule_for_item(args.get("pricing_rules"), item_details, args.get('item_code'))
			return item_details
		# ------------------------------------

		if not pricing_rule.validate_applied_rule:
			if pricing_rule.price_or_product_discount == "Price":
				dprint(f"DEBUG: Price Rule {pricing_rule.name} is of type 'Price' ...")
				apply_price_discount_rule(pricing_rule, item_details, args)
			else:
				dprint(f"DEBUG: Price Rule {pricing_rule.name} is of type 'Product' ...")
				get_product_discount_rule(pricing_rule, item_details, args, doc)
	# end of for loop

	dprint(f"Price Loops completed.  Rules applied = {applied_rules}")

	if not item_details.get("has_margin"):
		item_details.margin_type = None
		item_details.margin_rate_or_amount = 0.0

	item_details.has_pricing_rule = 1
	item_details.pricing_rules = frappe.as_json([d.pricing_rule for d in applied_rules])

	dprint(f"Final Results:\n{item_details}")
	dprint("\n**************** END PRICING************************\n")

	return item_details

def update_args_for_pricing_rule(args):
	"""
	Offical Upstream Function: But I'm unsure the point of it.
	"""
	if not (args.item_group and args.brand):
		try:
			args.item_group, args.brand = frappe.get_cached_value("Item", args.item_code, ["item_group", "brand"])
		except TypeError:
			# invalid item_code
			return None  # DH: original function returned a variable that didn't exist.
		if not args.item_group:
			frappe.throw(_("Item Group not mentioned in item master for item {0}").format(args.item_code))

	if args.transaction_type=="selling":
		if args.customer and not (args.customer_group and args.territory):

			if args.quotation_to and args.quotation_to != 'Customer':
				customer = frappe._dict()
			else:
				customer = frappe.get_cached_value("Customer", args.customer, ["customer_group", "territory"])

			if customer:
				args.customer_group, args.territory = customer

		args.supplier = args.supplier_group = None

	elif args.supplier and not args.supplier_group:
		args.supplier_group = frappe.get_cached_value("Supplier", args.supplier, "supplier_group")
		args.customer = args.customer_group = args.territory = None

def get_pricing_rule_details(args, pricing_rule):
	return frappe._dict({
		'pricing_rule': pricing_rule.name,
		'rate_or_discount': pricing_rule.rate_or_discount,
		'margin_type': pricing_rule.margin_type,
		'item_code': args.get("item_code"),
		'child_docname': args.get('child_docname')
	})

def apply_price_discount_rule(pricing_rule, item_details, args):
	dprint("DH: Entering function 'pricing_rule.apply_price_discount_rule()' ...")
	item_details.pricing_rule_for = pricing_rule.rate_or_discount

	if ((pricing_rule.margin_type in ['Amount', 'Percentage'] and pricing_rule.currency == args.currency)
			or (pricing_rule.margin_type == 'Percentage')):
		item_details.margin_type = pricing_rule.margin_type
		item_details.has_margin = True

		if pricing_rule.apply_multiple_pricing_rules and item_details.margin_rate_or_amount is not None:
			item_details.margin_rate_or_amount += pricing_rule.margin_rate_or_amount
		else:
			item_details.margin_rate_or_amount = pricing_rule.margin_rate_or_amount

	if pricing_rule.rate_or_discount == 'Rate':
		pricing_rule_rate = 0.0
		if pricing_rule.currency == args.currency:
			pricing_rule_rate = pricing_rule.rate

		if pricing_rule_rate:
			# Override already set price list rate (from item price)
			# if pricing_rule_rate > 0
			item_details.update({
				"price_list_rate": pricing_rule_rate * args.get("conversion_factor", 1),
			})
		item_details.update({
			"discount_percentage": 0.0
		})

	for apply_on in ['Discount Amount', 'Discount Percentage']:
		if pricing_rule.rate_or_discount != apply_on: continue

		field = frappe.scrub(apply_on)
		if pricing_rule.apply_discount_on_rate and item_details.get("discount_percentage"):
			# Apply discount on discounted rate
			item_details[field] += ((100 - item_details[field]) * (pricing_rule.get(field, 0) / 100))
		else:
			if field not in item_details:
				item_details.setdefault(field, 0)

			item_details[field] += (pricing_rule.get(field, 0)
				if pricing_rule else args.get(field, 0))

def remove_pricing_rule_for_item(pricing_rules, item_details, item_code=None):
	from erpnext.accounts.doctype.pricing_rule.utils import (get_applied_pricing_rules,
		get_pricing_rule_items)
	for d in get_applied_pricing_rules(pricing_rules):
		if not d or not frappe.db.exists("Pricing Rule", d): continue
		pricing_rule = frappe.get_cached_doc('Pricing Rule', d)

		if pricing_rule.price_or_product_discount == 'Price':
			if pricing_rule.rate_or_discount == 'Discount Percentage':
				item_details.discount_percentage = 0.0
				item_details.discount_amount = 0.0

			if pricing_rule.rate_or_discount == 'Discount Amount':
				item_details.discount_amount = 0.0

			if pricing_rule.margin_type in ['Percentage', 'Amount']:
				item_details.margin_rate_or_amount = 0.0
				item_details.margin_type = None
		elif pricing_rule.get('free_item'):
			item_details.remove_free_item = (item_code if pricing_rule.get('same_item')
				else pricing_rule.get('free_item'))

		if pricing_rule.get("mixed_conditions") or pricing_rule.get("apply_rule_on_other"):
			items = get_pricing_rule_items(pricing_rule)
			item_details.apply_on = (frappe.scrub(pricing_rule.apply_rule_on_other)
				if pricing_rule.apply_rule_on_other else frappe.scrub(pricing_rule.get('apply_on')))
			item_details.applied_on_items = ','.join(items)

	item_details.pricing_rules = ''

	return item_details

@frappe.whitelist()
def remove_pricing_rules(item_list):
	if isinstance(item_list, string_types):
		item_list = json.loads(item_list)

	out = []
	for item in item_list:
		item = frappe._dict(item)
		if item.get('pricing_rules'):
			out.append(remove_pricing_rule_for_item(item.get("pricing_rules"),
				item, item.item_code))

	return out

def set_transaction_type(args):
	if args.transaction_type:
		return
	# Farm To People: Added Daily Order.
	if args.doctype in ("Opportunity", "Quotation", "Sales Order", "Delivery Note", "Sales Invoice", "Daily Order"):
		args.transaction_type = "selling"
	elif args.doctype in ("Material Request", "Supplier Quotation", "Purchase Order",
		"Purchase Receipt", "Purchase Invoice"):
		args.transaction_type = "buying"
	elif args.customer:
		args.transaction_type = "selling"
	else:
		args.transaction_type = "buying"

@frappe.whitelist()
def make_pricing_rule(doctype, docname):
	doc = frappe.new_doc("Pricing Rule")
	doc.applicable_for = doctype
	doc.set(frappe.scrub(doctype), docname)
	doc.selling = 1 if doctype == "Customer" else 0
	doc.buying = 1 if doctype == "Supplier" else 0

	return doc

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_item_uoms(txt, filters):  # DH: Removing unused arguments
	items = [filters.get('value')]
	if filters.get('apply_on') != 'Item Code':
		field = frappe.scrub(filters.get('apply_on'))
		items = [d.name for d in frappe.db.get_all("Item", filters={field: filters.get('value')})]

	return frappe.get_all('UOM Conversion Detail', filters={
			'parent': ('in', items),
			'uom': ("like", "{0}%".format(txt))
		}, fields = ["distinct uom"], as_list=1)


def pricing_rule_matches_coupon_list(pricing_rule, coupon_code_list, verbose=False):
	"""
		Arguments:
			pricing_rule:  		Frappe dictionary
			coupon_code_list: 	Python List of Strings, representing Coupon Codes.
	"""

	from temporal import validate_datatype  # Late import from across Python modules.
	validate_datatype('coupon_code_list', coupon_code_list, list, mandatory=False)

	if pricing_rule.coupon_code_based != 1:
		return True

	if not coupon_code_list:
		return False	# no coupons provided, so no matches are possible.

	# This is some REALLY screwed up syntax for escaping SQL 'WHERE IN'.  But it appears
	# to be prolific throughout ERPNext.
	coupon_codes = coupon_code_list
	result = frappe.db.sql(""" SELECT Code.coupon_code
		FROM `tabCoupon Code`	AS Code
		INNER JOIN
			`tabCoupon Code Pricing Rule` 	CodePricingRule
		ON
			CodePricingRule.parenttype = 'Coupon Code'
		AND CodePricingRule.parent = Code.name
		AND CodePricingRule.pricing_rule = %s
		WHERE coupon_code in (%s) """ %
		('%s', ', '.join(['%s'] * len(coupon_codes))),
		values=tuple([pricing_rule.name] + coupon_codes),
		debug=False, explain=False)

	if (not result) or (not result[0]) or (not result[0][0]):
		if verbose:
			print(f"Not applying Pricing Rule = '{pricing_rule.name}'.  This rule requires a coupon, but none was found.")
		return False
	return True


def create_nth_order_list(customer_id, daily_order=None):
	"""
	Farm To People:  Return a list of Daily Orders, filtered, and sorted by Delivery Date ascending.
	"""
	from temporal import validate_datatype
	from ftp.ftp_module.doctype.daily_order.daily_order import DailyOrder

	validate_datatype("customer_id", customer_id, str, mandatory=True)
	validate_datatype("daily_order", daily_order, DailyOrder, mandatory=False)

	fields=['name', 'delivery_date', 'status_delivery']
	filters={ "status_delivery": ["not in", ['Paused', 'Skipped', 'Cancelled']],
	           "customer": customer_id
	}
	orders = frappe.get_list("Daily Order", filters=filters, fields=fields)

	if daily_order and daily_order not in [ foo['name'] for foo in orders ]:
		orders.append({"name": daily_order.name, "delivery_date": daily_order.delivery_date})

	ret = sorted(orders, key=lambda k: k['delivery_date'])
	return ret
