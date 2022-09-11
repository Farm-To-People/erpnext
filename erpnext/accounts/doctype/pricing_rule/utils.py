# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt

# For license information, please see license.txt

# Datahenge: Disabling some linting rules, because I don't want to re-write the entire module.
# pylint: disable=protected-access, consider-using-f-string, multiple-statements, invalid-name

from __future__ import unicode_literals

import copy
import datetime
import json


import frappe
from frappe import _, bold
from frappe.utils import cint, flt, get_link_to_form, getdate, today, fmt_money

from erpnext.setup.doctype.item_group.item_group import get_child_item_groups
from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses
from erpnext.stock.get_item_details import get_conversion_factor

# ---- Datahenge ----
DEBUG_MODE = False
VALIDATE_SCHEMAS = True

# -------------------


class MultiplePricingRuleConflict(frappe.ValidationError):
	pass

apply_on_table = {
	'Item Code': 'items',
	'Item Group': 'item_groups',
	'Brand': 'brands'
}

def get_pricing_rules(args, doc=None):
	"""
	Determine a list of Pricing Rules that "might" apply to these conditions.

	What are 'args'?  An indeterminate Dictionary full of "stuff".  It's awful how inconsistent it is.
	"""

	pricing_rules = []
	values =  {}

	# 1. Start adding some potential Pricing Rules to the list 'pricing_rules':
	for apply_on in ['Item Code', 'Item Group', 'Brand']:
		frappe.dprint(f"* Searching for pricing rules based on {apply_on}", check_env='FTP_DEBUG_PRICING_RULE')
		pricing_rules.extend(_get_pricing_rules(apply_on, args, values))
		if pricing_rules and not apply_multiple_pricing_rules(pricing_rules):
			frappe.dprint(f"Added {len(pricing_rules)} and will not search for any additional ones.", check_env='FTP_DEBUG_PRICING_RULE')
			break

	frappe.dprint(f"1. Possible rules include {[ each['name'] for each in pricing_rules] }", check_env='FTP_DEBUG_PRICING_RULE')

	pricing_rules = filter_pricing_rule_based_on_condition(pricing_rules, doc)
	if not pricing_rules:
		frappe.dprint("\u274c: get_pricing_rules(). No pricing rules found based on conditions.", check_env='FTP_DEBUG_PRICING_RULE')
		return []

	rules = []
	if apply_multiple_pricing_rules(pricing_rules):
		pricing_rules = sorted_by_priority(pricing_rules, args, doc)
		for pricing_rule in pricing_rules:
			if isinstance(pricing_rule, list):
				rules.extend(pricing_rule)
			else:
				rules.append(pricing_rule)
	else:
		# No need to apply multiple Pricing Rules.  There can only be One?
		# TODO: This function below is stripping out rules that should apply to Daily Order Lines.
		pricing_rule = filter_pricing_rules(args, pricing_rules, doc)
		if pricing_rule:
			rules.append(pricing_rule)

	if not rules:
		frappe.dprint("\u274c: get_pricing_rules(). No pricing rules found based on conditions.", check_env='FTP_DEBUG_PRICING_RULE')
	else:
		frappe.dprint(f"2. Final rules include {[ each['name'] for each in rules] }", check_env='FTP_DEBUG_PRICING_RULE')

	return rules

def sorted_by_priority(pricing_rules, args, doc=None):
	# If more than one pricing rules, then sort by priority
	pricing_rules_list = []
	pricing_rule_dict = {}

	for pricing_rule in pricing_rules:
		pricing_rule = filter_pricing_rules(args, pricing_rule, doc)
		if pricing_rule:
			if not pricing_rule.get('priority'):
				pricing_rule['priority'] = 1

			if pricing_rule.get('apply_multiple_pricing_rules'):
				pricing_rule_dict.setdefault(cint(pricing_rule.get("priority")), []).append(pricing_rule)

	for key in sorted(pricing_rule_dict):
		pricing_rules_list.extend(pricing_rule_dict.get(key))

	return pricing_rules_list or pricing_rules

def filter_pricing_rule_based_on_condition(pricing_rules, doc=None):
	"""
	This function is used by Client-side and Server-side for price calculations.
	"""
	# Datahenge: This code seems okay for Daily Orders, so far.

	# dprint(f"filter_pricing_rule_based_on_condition.  Potential Pricing Rules: {len(pricing_rules)}")

	filtered_pricing_rules = []
	if doc:
		for pricing_rule in pricing_rules:
			if pricing_rule.condition:
				try:
					if frappe.safe_eval(pricing_rule.condition, None, doc.as_dict()):
						filtered_pricing_rules.append(pricing_rule)
				except Exception:
					pass
			else:
				filtered_pricing_rules.append(pricing_rule)
	else:
		filtered_pricing_rules = pricing_rules

	# dprint(f"filter_pricing_rule_based_on_condition.  Result Pricing Rules: {len(pricing_rules)}")
	return filtered_pricing_rules

def _get_pricing_rules(apply_on, args, values):
	"""
	args:	a frappe.dict() class
	values:	another dictionary

	Purpose of this function is to add rules, based on "Apply On" values.
	"""
	# IMPORTANT: This code is one of the deepest 'origins' of Potential Pricing Rules.  It contains the SQL that fetches the potentials.
	# Datahenge: Added some validation:
	if (not apply_on) or apply_on not in ['Brand', 'Detail', 'Item Code', 'Item Group']:
		raise Exception("Argument 'apply_on' not one of (Brand, Detail, Item Code, Item Group) in function '_get_pricing_rules()'")
	if not args.transaction_type:
		raise ValueError("Missing mandatory args key = 'transaction_type'")

	apply_on_field = frappe.scrub(apply_on)
	if not args.get(apply_on_field):
		return []

	child_doc = '`tabPricing Rule {0}`'.format(apply_on)

	conditions = item_variant_condition = item_conditions = ""
	values[apply_on_field] = args.get(apply_on_field)
	if apply_on_field in ['item_code', 'brand']:
		item_conditions = "{child_doc}.{apply_on_field}= %({apply_on_field})s".format(child_doc=child_doc,
			apply_on_field = apply_on_field)

		if apply_on_field == 'item_code':
			if "variant_of" not in args:
				args.variant_of = frappe.get_cached_value("Item", args.item_code, "variant_of")

			if args.variant_of:
				item_variant_condition = ' or {child_doc}.item_code=%(variant_of)s '.format(child_doc=child_doc)
				values['variant_of'] = args.variant_of
	elif apply_on_field == 'item_group':
		item_conditions = _get_tree_conditions(args, "Item Group", child_doc, False)

	conditions += get_other_conditions(conditions, values, args)
	warehouse_conditions = _get_tree_conditions(args, "Warehouse", '`tabPricing Rule`')
	if warehouse_conditions:
		warehouse_conditions = " and {0}".format(warehouse_conditions)

	if not args.price_list:
		args.price_list = None

	conditions += " and ifnull(`tabPricing Rule`.for_price_list, '') in (%(price_list)s, '')"
	values["price_list"] = args.get("price_list")

	pricing_rules = frappe.db.sql("""select `tabPricing Rule`.*,
			{child_doc}.{apply_on_field}, {child_doc}.uom
		from `tabPricing Rule`, {child_doc}
		where ({item_conditions} or (`tabPricing Rule`.apply_rule_on_other is not null
			and `tabPricing Rule`.{apply_on_other_field}=%({apply_on_field})s) {item_variant_condition})
			and {child_doc}.parent = `tabPricing Rule`.name
			and `tabPricing Rule`.disable = 0 and
			`tabPricing Rule`.{transaction_type} = 1 {warehouse_cond} {conditions}
		order by `tabPricing Rule`.priority desc,
			`tabPricing Rule`.name desc""".format(
			child_doc = child_doc,
			apply_on_field = apply_on_field,
			item_conditions = item_conditions,
			item_variant_condition = item_variant_condition,
			transaction_type = args.transaction_type,
			warehouse_cond = warehouse_conditions,
			apply_on_other_field = "other_{0}".format(apply_on_field),
			conditions = conditions), values, as_dict=1, debug=False) or []

	if args.coupon_codes:
		# TODO: Filter out the Pricing Rules that are not limited by Coupon Codes.
		pass

	return pricing_rules

def apply_multiple_pricing_rules(pricing_rules):
	"""
	Datahenge: Returns a boolean True/False if ANY of the pricing_rules passed allows for Multiple Application.
	"""
	apply_multiple_rule = [d.apply_multiple_pricing_rules
		for d in pricing_rules if d.apply_multiple_pricing_rules]

	if not apply_multiple_rule: return False

	return True

def _get_tree_conditions(args, parenttype, table, allow_blank=True):
	field = frappe.scrub(parenttype)
	condition = ""
	if args.get(field):
		if not frappe.flags.tree_conditions:
			frappe.flags.tree_conditions = {}
		key = (parenttype, args.get(field))
		if key in frappe.flags.tree_conditions:
			return frappe.flags.tree_conditions[key]

		try:
			lft, rgt = frappe.db.get_value(parenttype, args.get(field), ["lft", "rgt"])
		except TypeError:
			frappe.throw(_("Invalid {0}").format(args.get(field)))

		parent_groups = frappe.db.sql_list("""select name from `tab%s`
			where lft<=%s and rgt>=%s""" % (parenttype, '%s', '%s'), (lft, rgt))

		if parenttype in ["Customer Group", "Item Group", "Territory"]:
			parent_field = "parent_{0}".format(frappe.scrub(parenttype))
			root_name = frappe.db.get_list(parenttype,
				{"is_group": 1, parent_field: ("is", "not set")}, "name", as_list=1, ignore_permissions=True)

			if root_name and root_name[0][0]:
				parent_groups.append(root_name[0][0])

		if parent_groups:
			if allow_blank: parent_groups.append('')
			condition = "ifnull({table}.{field}, '') in ({parent_groups})".format(
				table=table,
				field=field,
				parent_groups=", ".join(frappe.db.escape(d) for d in parent_groups)
			)

			frappe.flags.tree_conditions[key] = condition
	return condition

def get_other_conditions(conditions, values, args):
	for field in ["company", "customer", "supplier", "campaign", "sales_partner"]:
		if args.get(field):
			conditions += " and ifnull(`tabPricing Rule`.{0}, '') in (%({1})s, '')".format(field, field)
			values[field] = args.get(field)
		else:
			conditions += " and ifnull(`tabPricing Rule`.{0}, '') = ''".format(field)

	for parenttype in ["Customer Group", "Territory", "Supplier Group"]:
		group_condition = _get_tree_conditions(args, parenttype, '`tabPricing Rule`')
		if group_condition:
			conditions += " and " + group_condition

	if args.get("transaction_date"):
		conditions += """ and %(transaction_date)s between ifnull(`tabPricing Rule`.valid_from, '2000-01-01')
			and ifnull(`tabPricing Rule`.valid_upto, '2500-12-31')"""
		values['transaction_date'] = args.get('transaction_date')

	# July 7th, 2022: New field "price_date"
	if args.get("price_date"):
		conditions += """ and %(price_date)s between IFNULL(`tabPricing Rule`.valid_from_price_date, '2000-01-01')
			AND IFNULL(`tabPricing Rule`.valid_to_price_date, '2500-12-31')"""
		values['price_date'] = args.get('price_date')

	return conditions

def filter_pricing_rules(args, pricing_rules, doc=None):
	"""
	Datahenge: Given a List 'pricing_rules', which ones apply under the conditions of args + doc?

	Called -only- by JavaScript (to the best of my knowledge)
	"""

	# validate_args_schema_PY1(doc, args)  # need to ensure that arg contains enough information.

	args["for_shopping_cart"] = True  # DH (28 March) For the purpose of price calculations, this argument avoids conflicts due to lack of Priority.

	if not isinstance(pricing_rules, list):
		pricing_rules = [pricing_rules]
	original_pricing_rule = copy.copy(pricing_rules)

	# filter for qty
	if pricing_rules:
		stock_qty = flt(args.get('stock_qty'))
		amount = flt(args.get('price_list_rate')) * flt(args.get('qty'))

		if pricing_rules[0].apply_rule_on_other:
			field = frappe.scrub(pricing_rules[0].apply_rule_on_other)

			if (field and pricing_rules[0].get('other_' + field) != args.get(field)): return

		pr_doc = frappe.get_cached_doc('Pricing Rule', pricing_rules[0].name)

		if pricing_rules[0].mixed_conditions and doc:
			stock_qty, amount, items = get_qty_and_rate_for_mixed_conditions(doc, pr_doc, args)
			for pricing_rule_args in pricing_rules:
				pricing_rule_args.apply_rule_on_other_items = items

		elif pricing_rules[0].is_cumulative:
			items = [args.get(frappe.scrub(pr_doc.get('apply_on')))]
			data = get_qty_amount_data_for_cumulative(pr_doc, args, items)

			if data:
				stock_qty += data[0]
				amount += data[1]

		if pricing_rules[0].apply_rule_on_other and not pricing_rules[0].mixed_conditions and doc:
			pricing_rules = get_qty_and_rate_for_other_item(doc, pr_doc, pricing_rules) or []
		else:
			pricing_rules = filter_pricing_rules_for_qty_amount(stock_qty, amount, pricing_rules, args)

		if not pricing_rules:
			for d in original_pricing_rule:
				if not d.threshold_percentage: continue

				msg = validate_quantity_and_amount_for_suggestion(d, stock_qty,
					amount, args.get('item_code'), args.get('transaction_type'))

				if msg:
					return {'suggestion': msg, 'item_code': args.get('item_code')}

		# add variant_of property in pricing rule
		for p in pricing_rules:
			if p.item_code and args.variant_of:
				p.variant_of = args.variant_of
			else:
				p.variant_of = None

	# find pricing rule with highest priority
	if pricing_rules:
		max_priority = max(cint(p.priority) for p in pricing_rules)
		if max_priority:
			pricing_rules = list(filter(lambda x: cint(x.priority)==max_priority, pricing_rules))

	if pricing_rules and not isinstance(pricing_rules, list):
		pricing_rules = list(pricing_rules)

	if len(pricing_rules) > 1:
		rate_or_discount = list(set(d.rate_or_discount for d in pricing_rules))
		if len(rate_or_discount) == 1 and rate_or_discount[0] == "Discount Percentage":
			pricing_rules = list(filter(lambda x: x.for_price_list==args.price_list, pricing_rules)) \
				or pricing_rules

	if len(pricing_rules) > 1 and not args.for_shopping_cart:
		frappe.throw(_("Multiple Price Rules exists with same criteria, please resolve conflict by assigning priority. Price Rules: {0}")
			.format("\n".join(d.name for d in pricing_rules)), MultiplePricingRuleConflict)
	elif pricing_rules:
		return pricing_rules[0]

def validate_quantity_and_amount_for_suggestion(args, qty, amount, item_code, transaction_type):
	fieldname, msg = '', ''
	type_of_transaction = 'purchase' if transaction_type == 'buying' else 'sale'

	for field, value in {'min_qty': qty, 'min_amt': amount}.items():
		if (args.get(field) and value < args.get(field)
			and (args.get(field) - cint(args.get(field) * args.threshold_percentage * 0.01)) <= value):
			fieldname = field

	for field, value in {'max_qty': qty, 'max_amt': amount}.items():
		if (args.get(field) and value > args.get(field)
			and (args.get(field) + cint(args.get(field) * args.threshold_percentage * 0.01)) >= value):
			fieldname = field

	if fieldname:
		msg = (_("If you {0} {1} quantities of the item {2}, the scheme {3} will be applied on the item.")
			.format(type_of_transaction, args.get(fieldname), bold(item_code), bold(args.rule_description)))

		if fieldname in ['min_amt', 'max_amt']:
			msg = (_("If you {0} {1} worth item {2}, the scheme {3} will be applied on the item.")
				.format(type_of_transaction, fmt_money(args.get(fieldname), currency=args.get("currency")),
					bold(item_code), bold(args.rule_description)))

		frappe.msgprint(msg)

	return msg

def filter_pricing_rules_for_qty_amount(qty, rate, pricing_rules, args=None):
	rules = []

	for rule in pricing_rules:
		status = False
		conversion_factor = 1

		# Datahenge: Protect against scenario where UOM is filled-in, but there is no Item.
		if rule.get("uom") and rule.uom and rule.apply_on != "Item":
			continue  # Cannot specify a UOM without rules applying to Items
		if rule.get("uom") and not rule.item_code:
			continue  # Furthermore, you actually have to specify an Item.

		if rule.get("uom"):
			conversion_factor = get_conversion_factor(rule.item_code, rule.uom).get("conversion_factor", 1)

		if (flt(qty) >= (flt(rule.min_qty) * conversion_factor)
			and (flt(qty)<= (rule.max_qty * conversion_factor) if rule.max_qty else True)):
			status = True

		# if user has created item price against the transaction UOM
		if args and rule.get("uom") == args.get("uom"):
			conversion_factor = 1.0

		if status and (flt(rate) >= (flt(rule.min_amt) * conversion_factor)
			and (flt(rate)<= (rule.max_amt * conversion_factor) if rule.max_amt else True)):
			status = True
		else:
			status = False

		if status:
			rules.append(rule)

	return rules

def if_all_rules_same(pricing_rules, fields):
	all_rules_same = True
	val = [pricing_rules[0].get(k) for k in fields]
	for p in pricing_rules[1:]:
		if val != [p.get(k) for k in fields]:
			all_rules_same = False
			break

	return all_rules_same

def apply_internal_priority(pricing_rules, field_set, args):
	filtered_rules = []
	for field in field_set:
		if args.get(field):
			# filter function always returns a filter object even if empty
			# list conversion is necessary to check for an empty result
			filtered_rules = list(filter(lambda x: x.get(field)==args.get(field), pricing_rules))
			if filtered_rules: break

	return filtered_rules or pricing_rules

def get_qty_and_rate_for_mixed_conditions(doc, pr_doc, args):
	sum_qty, sum_amt = [0, 0]
	items = get_pricing_rule_items(pr_doc) or []
	apply_on = frappe.scrub(pr_doc.get('apply_on'))

	if items and doc.get("items"):
		for row in doc.get('items'):
			if (row.get(apply_on) or args.get(apply_on)) not in items: continue

			if pr_doc.mixed_conditions:
				amt = args.get('qty') * args.get("price_list_rate")
				if args.get("item_code") != row.get("item_code"):
					amt = flt(row.get('qty')) * flt(row.get("price_list_rate") or args.get("rate"))

				sum_qty += flt(row.get("stock_qty")) or flt(args.get("stock_qty")) or flt(args.get("qty"))
				sum_amt += amt

		if pr_doc.is_cumulative:
			data = get_qty_amount_data_for_cumulative(pr_doc, doc, items)

			if data and data[0]:
				sum_qty += data[0]
				sum_amt += data[1]

	return sum_qty, sum_amt, items

def get_qty_and_rate_for_other_item(doc, pr_doc, pricing_rules):
	"""
	This creates a list of Pricing Rules based on the 'Apply Rule on Other' field.
	"""
	items = get_pricing_rule_items(pr_doc)

	for row in doc.items:
		if row.get(frappe.scrub(pr_doc.apply_rule_on_other)) in items:
			pricing_rules = filter_pricing_rules_for_qty_amount(row.get("stock_qty"),
				row.get("amount"), pricing_rules, row)

			if pricing_rules and pricing_rules[0]:
				pricing_rules[0].apply_rule_on_other_items = items
				return pricing_rules


def get_qty_amount_data_for_cumulative(pr_doc, doc, items=[]):
	sum_qty, sum_amt = [0, 0]
	doctype = doc.get('parenttype') or doc.doctype

	date_field = 'transaction_date' if frappe.get_meta(doctype).has_field('transaction_date') else 'posting_date'

	child_doctype = '{0} Item'.format(doctype)
	apply_on = frappe.scrub(pr_doc.get('apply_on'))

	values = [pr_doc.valid_from, pr_doc.valid_upto]
	condition = ""

	if pr_doc.warehouse:
		warehouses = get_child_warehouses(pr_doc.warehouse)

		condition += """ and `tab{child_doc}`.warehouse in ({warehouses})
			""".format(child_doc=child_doctype, warehouses = ','.join(['%s'] * len(warehouses)))

		values.extend(warehouses)

	if items:
		condition = " and `tab{child_doc}`.{apply_on} in ({items})".format(child_doc = child_doctype,
			apply_on = apply_on, items = ','.join(['%s'] * len(items)))

		values.extend(items)

	data_set = frappe.db.sql(""" SELECT `tab{child_doc}`.stock_qty,
			`tab{child_doc}`.amount
		FROM `tab{child_doc}`, `tab{parent_doc}`
		WHERE
			`tab{child_doc}`.parent = `tab{parent_doc}`.name and `tab{parent_doc}`.{date_field}
			between %s and %s and `tab{parent_doc}`.docstatus = 1
			{condition} group by `tab{child_doc}`.name
	""".format(parent_doc = doctype,
		child_doc = child_doctype,
		condition = condition,
		date_field = date_field
	), tuple(values), as_dict=1)

	for data in data_set:
		sum_qty += data.get('stock_qty')
		sum_amt += data.get('amount')

	return [sum_qty, sum_amt]


def apply_pricing_rule_on_transaction(doc):
	"""
	Called By:  erpnext.controllers.accounts_controller.py
	"""
	# Datahenge: No longer used by Daily Orders; they have their own code.
	if doc.doctype == 'Daily Order':
		raise Exception("Daily Orders should not call standard ERPNext 'apply_pricing_rule_on_transaction'")
	conditions = "apply_on = 'Transaction'"

	values = {}
	conditions = get_other_conditions(conditions, values, doc)

	pricing_rules = frappe.db.sql(""" Select `tabPricing Rule`.* from `tabPricing Rule`
		where  {conditions} and `tabPricing Rule`.disable = 0
	""".format(conditions = conditions), values, as_dict=1)

	if pricing_rules:

		pricing_rules = remove_coupon_dependent_rules(pricing_rules, doc)  # FTP Coupon Code based Pricing Rules.
		pricing_rules = filter_pricing_rules_for_qty_amount(doc.total_qty,
			doc.total, pricing_rules)

		if not pricing_rules:
			remove_free_item(doc)

		for d in pricing_rules:

			# Farm To People: Exclude everything except Daily Orders.
			# Sales Invoices cannot handle the 2 simultaneous discounts of Net Total and Grand Total.
			if d.selling and doc.doctype not in ['Daily Order']:
				continue  # Do not run this code for Purchase Orders, Purchase Receipts, and Purchase Invoices.
			if d.buying and doc.doctype not in ['Purchase Order', 'Purchase Invoice']:
				continue  # Do not run this code for Purchase Orders, Purchase Receipts, and Purchase Invoices.

			if d.price_or_product_discount == 'Price':
				if d.apply_discount_on:
					doc.set('apply_discount_on', d.apply_discount_on)  # DH: This is bad; subsequent rules can flip this back and forth.

				for field in ['additional_discount_percentage', 'discount_amount']:
					pr_field = ('discount_percentage'
						if field == 'additional_discount_percentage' else field)

					if not d.get(pr_field): continue

					if d.validate_applied_rule and doc.get(field) is not None and doc.get(field) < d.get(pr_field):
						frappe.msgprint(_("User has not applied rule on the invoice {0}")
							.format(doc.name))
					else:
						doc.set(field, d.get(pr_field))

				doc.calculate_taxes_and_totals()
			elif d.price_or_product_discount == 'Product':
				item_details = frappe._dict({'parenttype': doc.doctype, 'free_item_data': []})
				get_product_discount_rule(d, item_details, doc=doc)
				apply_pricing_rule_for_free_items(doc, item_details.free_item_data)
				doc.set_missing_values()
				doc.calculate_taxes_and_totals()

def remove_free_item(doc):
	for d in doc.items:
		if d.is_free_item:
			doc.remove(d)

def get_applied_pricing_rules(pricing_rules):
	"""
	Converts a string 'pricing_rules' into something else?
	"""
	# Datahenge: As always, standard code has no type hints or any indication about function's purpose.
	if not pricing_rules:
		return []

	if pricing_rules.startswith('['):
		return json.loads(pricing_rules)
	else:
		return pricing_rules.split(',')


def get_product_discount_rule(pricing_rule, item_details, args=None, doc=None):
	free_item = pricing_rule.free_item
	if pricing_rule.same_item and pricing_rule.get("apply_on") != 'Transaction':
		free_item = item_details.item_code or args.item_code

	if not free_item:
		frappe.throw(_("Free item not set in the pricing rule {0}")
			.format(get_link_to_form("Pricing Rule", pricing_rule.name)))

	qty = pricing_rule.free_qty or 1
	if pricing_rule.is_recursive:
		transaction_qty = args.get('qty') if args else doc.total_qty
		if transaction_qty:
			qty = flt(transaction_qty) * qty

	free_item_data_args = {
		'item_code': free_item,
		'qty': qty,
		'pricing_rules': pricing_rule.name,
		'rate': pricing_rule.free_item_rate or 0,
		'price_list_rate': pricing_rule.free_item_rate or 0,
		'is_free_item': 1
	}

	item_data = frappe.get_cached_value('Item', free_item, ['item_name',
		'description', 'stock_uom'], as_dict=1)

	free_item_data_args.update(item_data)
	free_item_data_args['uom'] = pricing_rule.free_item_uom or item_data.stock_uom
	free_item_data_args['conversion_factor'] = get_conversion_factor(free_item,
		free_item_data_args['uom']).get("conversion_factor", 1)

	if item_details.get("parenttype") == 'Purchase Order':
		free_item_data_args['schedule_date'] = doc.schedule_date if doc else today()

	if item_details.get("parenttype") == 'Sales Order':
		free_item_data_args['delivery_date'] = doc.delivery_date if doc else today()

	item_details.free_item_data.append(free_item_data_args)

def apply_pricing_rule_for_free_items(doc, pricing_rule_args):
	if pricing_rule_args:
		items = tuple((d.item_code, d.pricing_rules) for d in doc.items if d.is_free_item)

		for args in pricing_rule_args:
			if not items or (args.get('item_code'), args.get('pricing_rules')) not in items:
				doc.append('items', args)

def get_pricing_rule_items(pr_doc):
	apply_on_data = []
	apply_on = frappe.scrub(pr_doc.get('apply_on'))

	pricing_rule_apply_on = apply_on_table.get(pr_doc.get('apply_on'))

	for d in pr_doc.get(pricing_rule_apply_on):
		if apply_on == 'item_group':
			apply_on_data.extend(get_child_item_groups(d.get(apply_on)))
		else:
			apply_on_data.append(d.get(apply_on))

	if pr_doc.apply_rule_on_other:
		apply_on = frappe.scrub(pr_doc.apply_rule_on_other)
		apply_on_data.append(pr_doc.get("other_" + apply_on))

	return list(set(apply_on_data))

def validate_coupon_code(coupon_name):
	coupon = frappe.get_doc("Coupon Code", coupon_name)

	if coupon.valid_from:
		if coupon.valid_from > getdate(today()):
			frappe.throw(_("Sorry, this coupon code's validity has not started"))
	elif coupon.valid_upto:
		if coupon.valid_upto < getdate(today()):
			frappe.throw(_("Sorry, this coupon code's validity has expired"))
	elif coupon.used >= coupon.maximum_use:
		frappe.throw(_("Sorry, this coupon code is no longer valid"))

def update_coupon_code_count(coupon_name, transaction_type):
	coupon=frappe.get_doc("Coupon Code", coupon_name)
	if coupon:
		if transaction_type=='used':
			if coupon.maximum_use == 0 or (coupon.used < coupon.maximum_use):    # Datahenge: Zero means unlimited usage.
				coupon.used=coupon.used+1
				coupon.save(ignore_permissions=True)
			else:
				frappe.throw(_(f"Coupon '{coupon.coupon_code}' used {coupon.used} times. Allowed quantity ({coupon.maximum_use}) is exhausted."))
		elif transaction_type=='cancelled':
			if coupon.used>0:
				coupon.used=coupon.used-1
				coupon.save(ignore_permissions=True)


# Datahenge/FTP Functions below


def is_coupon_based_pricing_rule_valid(pricing_rule, coupon_code_list, effective_date):
	"""
	Purpose: Given a Pricing Rule, Coupon Codes, and a Delivery Date, is this Price Rule valid?
	* Datahenge and FTP invention.
    * This should be Standard Functionality, but For Reasons Unknown, is strangely not.

	arguments:
		pricing_rule : a Python dictionary
		coupon_code_list : a Python List of coupon code names (strings)
	"""

	from temporal import validate_datatype
	from ftp.ftp_module.doctype.coupon_code_multi.coupon_code_multi import expand_coupon_multicodes

	validate_datatype('pricing_rules', pricing_rule, dict, mandatory=True)
	validate_datatype('coupon_code_list', coupon_code_list, list, mandatory=True)
	validate_datatype('coupon_code_list_element', coupon_code_list[0], str, mandatory=True)
	validate_datatype('effective_date', effective_date, datetime.date, mandatory=True)

	if not bool(pricing_rule['coupon_code_based']):
		raise Exception("Pricing rule is not Coupon Code based.  Function should not be called for this Pricing Rule.")

	# Expand Multi-Codes, and get a unique list of coupons.
	unique_codes = expand_coupon_multicodes(coupon_code_list)  # a Python Set of coupon code names (strings)

	result = False
	# Examine each coupon code
	for each_coupon_code in unique_codes:
		# frappe.dprint(f"* Checking if coupon code '{each_coupon_code}' enables pricing rule '{pricing_rule.name}' ...", check_env='FTP_DEBUG_PRICING_RULE')
		doc_coupon_code = frappe.get_doc("Coupon Code", each_coupon_code)

		if not doc_coupon_code.valid_for_date(effective_date):
			frappe.dprint(f"Coupon code {doc_coupon_code.name} is not valid for this Effective Date ({effective_date}).", check_env='FTP_DEBUG_PRICING_RULE')
			continue  # coupon code is not valid for this Effective Date, so this Pricing Rule cannot be active.

		# Each coupon code can 1 or more Pricing Rules (April 8th 2022)
		applicable_rules = [ row.pricing_rule for row in doc_coupon_code.pricing_rule ]
		if pricing_rule.name in applicable_rules:
			frappe.dprint(f"\u2713 Coupon code '{each_coupon_code}' enabled pricing rule '{pricing_rule.name}'", check_env='FTP_DEBUG_PRICING_RULE')
			result = True
			break

	return result


def remove_coupon_dependent_rules(pricing_rules, doc, effective_date=None, debug=False):
	"""
	Datahenge:  Writing this because no one else has done it.  This ensures that Coupon-based Pricing Rules
	do not alter documents like Delivery Notes, Sales Invoices, Purchase Orders, etc.

	pricing_rules = a Python List of Dictionary.
	doc = Document

	"""
	from temporal import any_to_date
	from temporal.core import get_system_datetime_now

	if not effective_date:
		effective_date = get_system_datetime_now().date()
	else:
		effective_date = any_to_date(effective_date)

	new_rules = []
	for pricing_rule in pricing_rules:

		# If Pricing Rule is not Coupon Based, then keep it.
		if not bool(pricing_rule['coupon_code_based']):
			new_rules.append(pricing_rule)
			if debug:
				print(f"Retaining Pricing Rule '{pricing_rule.name}', because it does not require a Coupon Code.")
			continue

		# For coupon-based Rules, if this isn't a Daily or Sales Order, throw out this Pricing Rule.
		if doc.doctype not in ['Daily Order', 'Sales Order']:
			if debug:
				print(f"Removing coupon-based Pricing Rule '{pricing_rule.name}', because this {doc.doctype} isn't a Daily/Sales Order)")
			continue

		# Compare document's Coupon Code(s) to the ones required by the Pricing Rule.
		coupon_code_list = [ row.coupon_code for row in doc.coupon_code_set]
		if not coupon_code_list:
			if debug:
				print(f"Order has no Coupons; coupon-based Pricing Rule '{pricing_rule.name}' cannot be activated.")
			continue

		if is_coupon_based_pricing_rule_valid(pricing_rule, coupon_code_list, effective_date):
			new_rules.append(pricing_rule)
		else:
			if debug:
				print(f"  Coupon-based Pricing Rule '{pricing_rule.name}' cannot be activated by these Coupons: {coupon_code_list}.")

	return new_rules

# pylint: disable=pointless-string-statement
"""
def validate_args_schema_PY1(doc, args):

	from schema import Schema, And, Or, Optional
	NoneType = type(None)

	print(f"Document: {doc}")
	print(f"Length of args = {len(args)}")

	if not doc:
		# I've seen 40 keys with no Document passed.
		return  # not going to bother validating this scenario just yet.

	if doc.doctype not in ('Daily Order', 'Daily Order Item'):
		# When called via JavaScript with a SalesOrder, I've seen 34 keys, 36 keys, 70 keys, and 182 keys.
		# It's driving me crazy how inconsistent the arguments are, for the same exact function.
		return

	result_schema = Schema({
		'customer': And(str, len),
		'customer_group': Or(str, NoneType),
		'territory': Or(str, NoneType),
		'currency': And(str, len),
		'conversion_rate': Or(int, float),
		'price_list': And(str, len),
		'price_list_currency': And(str, len),
		'plc_conversion_rate': Or(int, float),
		'company': And(str, len),
		'transaction_date': And(str, len),
		'ignore_pricing_rule': int,
		'doctype': And(str,len),
		'name': And(str, len),
		Optional('is_return'): int,
		'update_stock': int,
		Optional('pos_profile'): str,
		'coupon_codes': list,
		'transaction_type': And(str,len),
		'child_docname': And(str, len),
		'item_code': And(str, len),
		'item_group': And(str, len),
		'qty': Or(int, float),
		'stock_qty': Or(int, float),
		'uom': And(str, len),
		'stock_uom': And(str, len),
		Optional('parenttype'): And(str, len),
		Optional('parent'): And(str, len),
		Optional('pricing_rules'): Or(str, list),
		'warehouse': And(str, len),
		'price_list_rate': Or(int, float),
		'conversion_factor': Or(int, float),
		Optional('margin_rate_or_amount'): Or(int, float),
		'brand': Or(NoneType, str),
		'supplier': Or(NoneType, str),
		'supplier_group': Or(NoneType, str),
		'variant_of': Or(NoneType, str)
		})

	result_schema.validate(args)
"""
