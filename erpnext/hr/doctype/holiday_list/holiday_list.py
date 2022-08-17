
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import json
import frappe
from frappe.utils import cint, getdate, formatdate, today
from frappe import throw, _
from frappe.model.document import Document

class OverlapError(frappe.ValidationError):
	pass

class HolidayList(Document):
	def validate(self):
		self.validate_days()
		self.total_holidays = len(self.holidays)

	@frappe.whitelist()
	def get_weekly_off_dates(self):
		self.validate_values()
		date_list = self.get_weekly_off_date_list(self.from_date, self.to_date)
		last_idx = max([cint(d.idx) for d in self.get("holidays")] or [0,])
		for i, d in enumerate(date_list):
			ch = self.append('holidays', {})
			ch.description = self.weekly_off
			ch.holiday_date = d
			ch.weekly_off = 1
			ch.idx = last_idx + i + 1

	def validate_values(self):
		if not self.weekly_off:
			throw(_("Please select weekly off day"))


	def validate_days(self):
		if getdate(self.from_date) > getdate(self.to_date):
			throw(_("To Date cannot be before From Date"))

		for day in self.get("holidays"):
			if not (getdate(self.from_date) <= getdate(day.holiday_date) <= getdate(self.to_date)):
				frappe.throw(_("The holiday on {0} is not between From Date and To Date").format(formatdate(day.holiday_date)))

	def get_weekly_off_date_list(self, start_date, end_date):
		start_date, end_date = getdate(start_date), getdate(end_date)

		from dateutil import relativedelta
		from datetime import timedelta
		import calendar

		date_list = []
		existing_date_list = []
		weekday = getattr(calendar, (self.weekly_off).upper())
		reference_date = start_date + relativedelta.relativedelta(weekday=weekday)

		existing_date_list = [getdate(holiday.holiday_date) for holiday in self.get("holidays")]

		while reference_date <= end_date:
			if reference_date not in existing_date_list:
				date_list.append(reference_date)
			reference_date += timedelta(days=7)

		return date_list

	@frappe.whitelist()
	def clear_table(self):
		self.set('holidays', [])

	@frappe.whitelist()
	def shift_daily_orders(self):

		for each_holiday in self.holidays:
			frappe.msgprint(f"Enqueued a background job for Holiday shift from {each_holiday.holiday_date} to {each_holiday.shift_to_date}...")
			frappe.enqueue(
				method="erpnext.hr.doctype.holiday_list.holiday_list.enqueue_holiday_shift",
				queue="default",
				timeout="3600",
				is_async=True,
				holiday_date=each_holiday.holiday_date,
				shift_to_date=each_holiday.shift_to_date
			)
		# end of function

def on_doctype_update():
	""" Create additional indexes and constraints. """
	# Yes, this code belongs here, outside of the Document class.  :/
	# Holiday child document.
	frappe.db.add_index("Holiday", ["parent", "holiday_date"], index_name='holiday_date_idx')


@frappe.whitelist()
def get_events(start, end, filters=None):
	"""Returns events for Gantt / Calendar view rendering.

	:param start: Start date-time.
	:param end: End date-time.
	:param filters: Filters (JSON).
	"""
	if filters:
		filters = json.loads(filters)
	else:
		filters = []

	if start:
		filters.append(['Holiday', 'holiday_date', '>', getdate(start)])
	if end:
		filters.append(['Holiday', 'holiday_date', '<', getdate(end)])

	return frappe.get_list('Holiday List',
		fields=['name', '`tabHoliday`.holiday_date', '`tabHoliday`.description', '`tabHoliday List`.color'],
		filters = filters,
		update={"allDay": 1})


def is_holiday(holiday_list, date=today()):
	"""Returns true if the given date is a holiday in the given holiday list
	"""
	if holiday_list:
		return bool(frappe.get_all('Holiday List',
			dict(name=holiday_list, holiday_date=date)))
	else:
		return False


def enqueue_holiday_shift(holiday_date, shift_to_date):
	"""
	This function is normally enqueued by HolidayList.shift_daily_orders()
	"""
	from ftp.ftp_module.doctype.customer_activity_log.customer_activity_log import new_error_log
	from ftp.ftp_module.generics import get_calculation_date
	from temporal import any_to_date

	if any_to_date(holiday_date) < get_calculation_date():
		frappe.msgprint(f"Holiday {holiday_date} is in the past; cannot alter Orders.")
		return

	frappe.msgprint(f"Shifting from {holiday_date} to {shift_to_date}")
	daily_order_names = frappe.get_list("Daily Order", filters={"delivery_date": holiday_date}, pluck="name")
	print(f"Holiday Shift: Start to process {len(daily_order_names)} orders...")
	for each_name in daily_order_names:
		try:
			doc_daily_order = frappe.get_doc("Daily Order", each_name)
			print(f"Holiday shift for Daily Order = {doc_daily_order.name} ...")
			doc_daily_order.change_order_delivery_date(shift_to_date, validate_only=False,
			                                           raise_on_errors=True, ignore_stock_quantity=True)
			print("...success")
			frappe.db.commit()

		except Exception as ex:
			frappe.db.rollback()
			new_error_log(customer_key=doc_daily_order.customer, activity_type='Change Order Date', 
				short_message="Holiday Shift", long_message=ex, ref_doctype='Daily Order',
				ref_docname = doc_daily_order.name)
			print(ex)
			continue

	print(f"Holiday Shift: Finished processing {len(daily_order_names)} orders...")
