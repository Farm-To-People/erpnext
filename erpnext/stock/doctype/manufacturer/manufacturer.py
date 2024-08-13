# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import json
import frappe
from frappe.contacts.address_and_contact import load_address_and_contact  #, delete_contact_and_address
from frappe.model.document import Document

class Manufacturer(Document):
	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def on_update(self):
		"""
		Update Sanity CMS whenever the Manufacturer is edited.
		"""
		from ftp.ftp_sanity.manufacturer import update_sanity_producer
		update_sanity_producer(self)

	def on_change(self):
		# Late imports due to cross-module dependency:
		from ftp.ftp_invent.redis.manufacturer_attributes import rewrite_attributes_by_manufacturer

		try:
			rewrite_attributes_by_manufacturer(self.name)  # Updates the Middleware Redis, including Filter Values.
		except Exception as e:
			frappe.msgprint(f"{e}", to_console=True)

	@frappe.whitelist()
	def get_sanity_record(self):
		"""
		Ask Sanity for data about this Manufacturer.
		"""
		from ftp.ftp_sanity.manufacturer import SanityProducer
		return SanityProducer.get_by_key(self.name)

	@frappe.whitelist()
	def button_show_middleware_redis(self):
		"""
		This button creates a pop-up in the browser, Manufacturer data stored in Middleware Redis.
		"""
		from ftp.ftp_module.doctype.tcp_connection.tcp_connection import TCPConnection
		redis_key = f"producer_attributes|{self.name}"
		connection = TCPConnection.find_by_purpose("Middleware Cache").create_redis_connection()
		if not connection.exists(redis_key):
			raise RuntimeError(f"Unable to find key in Middleware Redis: '{redis_key}'")

		redis_data = connection.hgetall(redis_key)

		results = json.dumps(redis_data, indent=4)  # convert from List of Dictionary, to JSON.
		results = results.replace('\n','<br>')  # Convert to HTML.
		results = results.replace(' ','&nbsp;')
		results = "<b>Middleware Redis:</b><br>" + results
		frappe.msgprint(results)
