from frappe import qb


def execute():
	"""
	Clear `tabSingles` and Payment Reconciliation tables of values
	"""
	singles = qb.DocType("Singles")
	qb.from_(singles).delete().where(singles.doctype == "Payment Reconciliation").run()
	doctypes = [
		"Payment Reconciliation Invoice",
		"Payment Reconciliation Payment",
		"Payment Reconciliation Allocation",
	]
	for x in doctypes:
		dt = qb.DocType(x)
		try:
			qb.from_(dt).delete().run()
		except Exception as ex:
			print(f"Error while trying to delete SQL data for DocType '{dt}' : {ex}")
