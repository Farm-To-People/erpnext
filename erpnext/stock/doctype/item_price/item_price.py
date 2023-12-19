# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document

from temporal import MIN_DATE, MAX_DATE, any_to_date

class ItemPriceDuplicateItem(frappe.ValidationError):
	pass


class ItemPrice(Document):

	def before_validate(self):
		# Farm to People Rule : No Customer-Specific Pricing allowed in Item Price table.
		# Not creating a separate flag "Deposit"; just use the new "Price Type"
		self.customer = None

	def validate(self):
		# FTP Rules for choosing which Price:
		# 1. Allow smart date overlapping (specific ranges > empties)
		# 2. Specific ranges can never overlap other specific ranges.
		# 3. Empties can never overlap other empties.  This is handled by check_duplicates()

		# Datahenge: Not sure why self.validate_item() is necessary, when we have built-in Link Validation.
		# self.validate_item()

		from ftp.ftp_invent import validate_uom_compatibility  # Late import due to Cross Module dependency.

		self.validate_dates()
		self.update_price_list_details()  # <---- This can change the Buying and Selling booleans

		if self.selling and self.item_price_type not in ('Selling', 'Deposit'):
			frappe.throw(_("Mismatch between 'Price List' and 'Price Type'"))
		elif self.buying and self.item_price_type != 'Buying':
			frappe.throw(_("Mismatch between 'Price List' and 'Price Type'"))

		self.update_item_details()
		self.check_duplicates()  # standard Frappe function.
		# self.validate_overlapping_prices_ftp()  # commented out July 2022, because it was causing headaches for FTP data entry.

		# FTP - Validate units of measure conversion:
		stock_uom = frappe.get_value("Item", self.item_code, "stock_uom")
		if not validate_uom_compatibility(stock_uom, self.uom, self.item_code):
			raise ValueError(f"Item is missing a conversion factor from UOM '{self.uom}' to stock UOM '{stock_uom}'.")

	def validate_item(self):
		if not frappe.db.exists("Item", self.item_code):
			frappe.throw(_("Item {0} not found.").format(self.item_code))

	def validate_dates(self):
		# Delivery Dates
		if self.valid_from and self.valid_upto:
			if any_to_date(self.valid_from) > any_to_date(self.valid_upto):
				frappe.throw(_(f"Valid From Date ({self.valid_from}) must be less than Valid Upto Date ({self.valid_upto})."))
		# Price Dates
		if self.valid_from_price_date and self.valid_to_price_date:
			if any_to_date(self.valid_from_price_date) > any_to_date(self.valid_to_price_date):
				frappe.throw(_("'Valid From Price Date' must be less than 'Valid To Price Date'"))

	def update_price_list_details(self):
		if self.price_list:
			price_list_details = frappe.db.get_value("Price List",
				{"name": self.price_list, "enabled": 1},
				["buying", "selling", "currency"])

			if not price_list_details:
				link = frappe.utils.get_link_to_form('Price List', self.price_list)
				frappe.throw(f"The price list {link} does not exist or is disabled")

			self.buying, self.selling, self.currency = price_list_details

	def update_item_details(self):
		if self.item_code:
			self.item_name, self.item_description = frappe.db.get_value("Item", self.item_code,["item_name", "description"])

	def check_duplicates(self):
		conditions = """where item_code = %(item_code)s and price_list = %(price_list)s and name != %(name)s"""

		for field in [
			"uom",
			"valid_from",
			"valid_upto",
			"valid_from_price_date",
			"valid_to_price_date",
			"packing_unit",
			"customer",
			"supplier",
			"batch_no"]:
			if self.get(field):
				conditions += f" and {field} = %({field})s "
			else:
				conditions += f"and (isnull({field}) or {field} = '')"

		price_list_rate = frappe.db.sql(f"""
				SELECT price_list_rate
				FROM `tabItem Price`
				{conditions}
			""",
			self.as_dict())

		if price_list_rate:
			frappe.throw(_("Item Price appears multiple times based on Price List, Supplier/Customer, Currency, Item, Batch, UOM, Qty, and Dates."), ItemPriceDuplicateItem,)

	def before_save(self):
		# Datahenge: Improved on this, so it doesn't wipe out the Reference field.
		if self.selling and self.customer and not self.reference:
			self.reference = self.customer
		if self.buying and self.supplier and not self.reference:
			self.reference = self.supplier

		if self.selling and not self.buying:
			# if only selling then remove supplier
			self.supplier = None
		if self.buying and not self.selling:
			# if only buying then remove customer
			self.customer = None

	def validate_overlapping_prices_ftp(self):
		"""
		If this Item Price record overlaps with others, throw an error.
		"""
		overlapping_prices = self.get_overlapping_prices_ftp()
		if overlapping_prices[0]:
			raise ValueError(f"Overlap with related Item Price name '{overlapping_prices[0]}'<br>Date Range: {overlapping_prices[1]} to {overlapping_prices[2]}")

	def get_overlapping_prices_ftp(self) -> tuple:
		"""
		Search for adjacent Item Prices.  For each found, verify there is no overlap with the current record.
		"""
		# 1. For the current Item Price, convert empty/null dates into either MIN_DATE (beginning of time) or MAX_DATE (end of time)
		this_valid_from_delivery_date = any_to_date(self.valid_from or MIN_DATE)
		this_valid_to_delivery_date = any_to_date(self.valid_upto or MAX_DATE)
		this_valid_from_price_date = any_to_date(self.valid_from_price_date or MIN_DATE)
		this_valid_to_price_date = any_to_date(self.valid_to_price_date or MAX_DATE)

		# 2. Read the related Item Prices from the SQL database.
		fields = [ "name", "item_code", "valid_from", "valid_upto", "valid_from_price_date", "valid_to_price_date" ]
		filters = { "item_code": self.item_code,
		            "selling": self.selling,
					"buying": self.buying,
		            "name": ["!=", self.name]  # do not fetch this record itself
		}
		if self.customer:
			filters['customer'] = self.customer
		related_records = frappe.get_list("Item Price", filters=filters, fields=fields)

		# 3. Loop through the related, adjacent Item Prices.
		for each_record in related_records:
			# Convert NULL dates into minimums (beginning of time) or maximums (end of time)
			overlaps = (
				this_valid_from_delivery_date <= (each_record.valid_upto or MAX_DATE) and \
				this_valid_to_delivery_date >= (each_record.valid_from or MIN_DATE) and \
				this_valid_from_price_date <= (each_record.valid_to_price_date or MAX_DATE) and \
				this_valid_to_price_date >= (each_record.valid_from_price_date or MIN_DATE)
			)
			if overlaps:
				return each_record.name, each_record.valid_from, each_record.valid_upto, each_record.valid_from_price_date, each_record.valid_to_price_date

		return None, None, None, None, None

	def on_change(self):
		"""
		Farm To People: Update website item availability (Redis) after Item Price touched.
		"""
		from ftp.ftp_invent.redis.api import try_update_redis_inventory
		from ftp.ftp_sanity.products import update_sanity_product
		if self.selling:
			try:
				try_update_redis_inventory(item_code=self.item_code)
			except Exception as ex:
				print(ex)
				frappe.msgprint("Unable to update Redis.<br>To resolve, continue editing Item Prices.  There should be an active Selling Price for the next 28 days.")
		update_sanity_product(self.item_code)

	def after_delete(self):
		"""
		Farm To People: Update redis after Item Price touched.
		"""
		from ftp.ftp_invent.redis.api import try_update_redis_inventory
		from ftp.ftp_sanity.products import update_sanity_product

		if self.selling:
			try:
				try_update_redis_inventory(item_code=self.item_code)
			except Exception as ex:
				print(ex)
				frappe.msgprint("Unable to update Redis.<br>To resolve, continue editing Item Prices.  There should be an active Selling Price for the next 28 days.")
		update_sanity_product(self.item_code)

	@frappe.whitelist()
	def validate_by_item_code(self):
		"""
		Validates the -entire- Item Code, not just this single record.
		Caller: ERP UI button at the top of an Item Price.
		"""
		from ftp.utilities.pricing import ItemPriceValidation
		# self.validate_overlapping_prices_ftp()
		ItemPriceValidation(self.item_code).validate_item_prices()
