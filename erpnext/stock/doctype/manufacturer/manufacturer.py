# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
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

	@frappe.whitelist()
	def get_sanity_record(self):
		"""
		Ask Sanity for data about this Manufacturer.
		"""
		from ftp.ftp_sanity.manufacturer import SanityProducer
		return SanityProducer.get_by_key(self.name)
