""" weighted_discounts.py """

import frappe

@frappe.whitelist()
def show_weighted_discounts(item_code, discount_price, discount_per_qty, as_of_date, min_qty=2, max_qty=7):

	from ftp.utilities.pricing import item_standard_sales_price
	standard_price = item_standard_sales_price(item_code, delivery_date=as_of_date)

	# Called via JavaScript, so have to fix the loose typing.
	discount_price = frappe.utils.flt(discount_price)
	discount_per_qty = int(discount_per_qty)

	message = ""
	for quantity in range(min_qty, max_qty+1):
		if quantity % discount_per_qty == 0:
			message += f"Quantity {quantity} : Pricing Rule price: ${discount_price:.2f}\n"
			continue

		remainder = quantity % discount_per_qty
		# print(f"Remainder: {remainder}")

		unit_price = (
		((quantity-remainder) * discount_price) + \
		(remainder * standard_price)
		) / quantity

		pricing_rule_price = round(unit_price,2)
		message += f"Quantity {quantity} : Pricing Rule price: ${pricing_rule_price:.2f}\n"

	frappe.msgprint(message)
