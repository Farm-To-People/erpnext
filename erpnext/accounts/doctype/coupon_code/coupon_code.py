# -*- coding: utf-8 -*-
# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (strip)
from frappe.utils import getdate


class CouponCode(Document):


	def before_rename(self, olddn, newdn, merge=False):
		raise Exception("Coupon Codes cannot be renamed (please see Shelby)")

	def autoname(self):
		self.coupon_code = strip(self.coupon_code)
		self.name = self.coupon_code

		if not self.coupon_code:
			if self.coupon_type == "Promotional":
				self.coupon_code =''.join(i for i in self.coupon_code if not i.isdigit())[0:8].upper()
			elif self.coupon_type == "Gift Card":
				self.coupon_code = frappe.generate_hash()[:10].upper()

	def validate(self):
		if self.coupon_type == "Gift Card":
			self.maximum_use = 1
			if not self.customer:
				frappe.throw(_("Please select the customer."))

	# DATAHENGE
	def valid_for_date(self, any_date):
		"""
		Is coupon code valid for a particular date range?
		"""
		if not any_date:
			raise ValueError("Argument 'any_date' is mandatory for this function.")
		if isinstance(any_date, str):
			any_date = getdate(any_date)
		from_date = self.valid_from or getdate('2000-01-01')
		to_date = self.valid_upto or getdate('2500-12-31')
		if from_date <= any_date <= to_date:
			return True
		return False
