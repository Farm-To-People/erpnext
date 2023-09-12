# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# Copyright (c) 2023, Farm To People LLC and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document
from frappe.utils import (strip)
from frappe.utils import getdate

# Farm To People:  Vanilla ERPNext had 4 different fields:
# 1. name
# 2. coupon_name
# 3. coupon_code
# 4. description

# This is very confusing, so we've removed 'coupon_name'

class CouponCode(Document):


	def before_rename(self, olddn, newdn, merge=False):  # pylint: disable=unused-argument
		self.coupon_code = newdn

	def autoname(self):
		self.coupon_code = strip(self.coupon_code)
		self.name = self.coupon_code

		if (not self.coupon_code) and self.coupon_type == "Promotional":
			self.coupon_code =''.join(i for i in self.coupon_code if not i.isdigit())[0:8].upper()
			# elif self.coupon_type == "Gift Card":
			#	self.coupon_code = frappe.generate_hash()[:10].upper()

	def validate(self):
		#if self.coupon_type == "Gift Card":
		#	self.maximum_use = 1
		#	if not self.customer:
		#		frappe.throw(_("Please select the customer."))
		if self.coupon_type == 'Multi-Code':  # Farm To People
			self._validate_multi()

	def _validate_multi(self):
		# Farm To People custom function.
		if len(self.multi_coupon_codes) < 2:
			frappe.throw("A coupon code of type 'Multi-Code' must have at least 2 member coupons.")
		for code in self.multi_coupon_codes:
			code.validate()

	def valid_for_date(self, any_date):
		"""
		Is coupon code valid for a particular date range?
		"""
		# Farm To People
		if not any_date:
			raise ValueError("Argument 'any_date' is mandatory for this function.")
		if isinstance(any_date, str):
			any_date = getdate(any_date)
		from_date = self.valid_from or getdate('2000-01-01')
		to_date = self.valid_upto or getdate('2500-12-31')
		if from_date <= any_date <= to_date:
			return True
		return False

	def recalc_usage(self):
		"""
		Datahenge: Recalculate the Coupon Code usage.
		"""
		# TODO: Make it so.

	def for_nth_order_position(self) -> int:
		"""
		Is this coupon code associated with an Nth Order Only pricing rule?
		"""

		query = """
			SELECT
				Coupon.name
				,PricingRule.name
				,PricingRule.nth_order_only
			FROM
				`tabCoupon Code`		AS Coupon
				
			INNER JOIN
				`tabCoupon Code Pricing Rule`		AS PricingRuleMap
			ON
				PricingRuleMap.parenttype = 'Coupon Code'
			AND PricingRuleMap.parent = Coupon.name

			INNER JOIN
				`tabPricing Rule`		AS PricingRule
			ON
				PricingRule.name = PricingRuleMap.pricing_rule
			AND PricingRule.selling = 1
			AND IFNULL(nth_order_only,0) > 0

			WHERE
				Coupon.coupon_code = %(coupon_code)s
			LIMIT 1;
		"""

		results = frappe.db.sql(query, values={ "coupon_code": self.name }, as_dict=True)
		if not results or not results[0]:
			return None
		return int(results[0]["nth_order_only"])

# Yes, 'on_doctype_update' belongs here, outside the Document class.
def on_doctype_update():
	"""
	Create additional indexes and constraints.
	"""
	# FTP : Performance index for finding a customer's Referral Code
	frappe.db.add_index("Coupon Code", ["coupon_type", "customer", "valid_upto"], index_name="referral_code_IDX")
