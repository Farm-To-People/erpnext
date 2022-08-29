# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# Copyright (c) 2022, Farm To People LLC and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
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


	def before_rename(self, olddn, newdn, merge=False):
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

# Farm To People
def calc_coupon_code_type(coupon_code_str):
	"""
	Returns a Result, where the message is one of 3 values:
		* Standard
		* Referral
		* Error
	"""

	from ftp.ftp_module.generics import Result

	# Cannot use 'frappe.db.exists' because we're filtering by other than 'name'
	coupon_code = frappe.db.get_value("Coupon Code", filters={"coupon_code": coupon_code_str}, fieldname="coupon_code")
	if coupon_code:
		return Result(success=True, message={"coupon_type": "Standard", "reference": coupon_code})

	# Cannot use 'frappe.db.exists' because we're filtering by other than 'name'
	customer = frappe.db.get_value("Customer", filters={"referral_code": coupon_code_str}, fieldname="name")
	if bool(customer):
		return Result(success=True, message={"coupon_type": "Referral", "reference": customer })

	# String is not a known Coupon Code or Referral Code:
	return Result(success=False, message=f"Error: Value '{coupon_code_str}' is neither a Coupon or Referral code.")
