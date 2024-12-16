# -*- coding: utf-8 -*-
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import json
import frappe
from frappe.contacts.address_and_contact import load_address_and_contact  #, delete_contact_and_address
from frappe.model.document import Document
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

class Manufacturer(Document):

	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)

	def on_update(self):
		from ftp.ftp_website.api import manufacturer_data_changed  # late import due to cross-module dependency
		manufacturer_data_changed(self.name)  # FTP : Call custom code whenever the Manufacturer is updated.

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


# Reference location for distance calculation
REFERENCE_ADDRESS = "100 Flushing Avenue, NY"
REFERENCE_COORDINATES = (40.6987, -73.9553)  # Coordinates of the reference address

@frappe.whitelist()
def update_manufacturer_from_address(manufacturer_name):
    # Fetch the Manufacturer document
    manufacturer = frappe.get_doc("Manufacturer", manufacturer_name)
    
    # Fetch the primary address linked to the Manufacturer
    address_links = frappe.get_all(
        "Dynamic Link", filters={
            "link_doctype": "Manufacturer",
            "link_name": manufacturer_name,
            "parenttype": "Address"
        }, fields=["parent"]
    )
    
    if not address_links:
        frappe.msgprint("No address linked to this Manufacturer.")
        return

    # Get the first address
    address = frappe.get_doc("Address", address_links[0].get("parent"))
    full_address = f"{address.address_line1}, {address.city}, {address.state}, {address.country}"

    # Validate the state
    valid_states = get_valid_states_and_countries()
    if address.state not in valid_states:
        frappe.throw(f"Invalid state: {address.state}. Please provide a valid US state or country code.")

	# Install geopy on bench python virtual env using "pip install geopy"
    # Geocode the address to get Latitude and Longitude
    geolocator = Nominatim(user_agent="erpnext_app")
    location = geolocator.geocode(full_address)
    if not location:
        frappe.throw(f"Unable to fetch coordinates for address: {full_address}")

    # Calculate distance from reference point
    manufacturer_coordinates = (location.latitude, location.longitude)
    distance = geodesic(REFERENCE_COORDINATES, manufacturer_coordinates).miles

    # Update Manufacturer fields
    manufacturer.state = address.state
    manufacturer.latitude = location.latitude
    manufacturer.longitude = location.longitude
    manufacturer.distance = distance
    manufacturer.save()

    frappe.msgprint("Manufacturer details updated successfully.")


def get_valid_states_and_countries():
    """
    Returns a list of valid US state codes and country codes.
    """
    # US State and Territory codes
    state_codes = [
        "AL", "AK", "AS", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "GU", "HI", "ID",
        "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
        "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "MP", "OH", "OK", "OR", "PA", "PR", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VI", "VA", "WA", "WV", "WI", "WY"
    ]

    # Add country codes (if needed)
    country_codes = ["US", "CA", "MX"]  # Add other codes as required
    return state_codes + country_codes


@frappe.whitelist()
def trigger_update_on_address_update(doc, method):
    """
    Hook function triggered when an Address linked to a Manufacturer is updated.
    """
    address_links = frappe.get_all(
        "Dynamic Link", filters={
            "parent": doc.name,
            "link_doctype": "Manufacturer"
        }, fields=["link_name"]
    )
    for link in address_links:
        update_manufacturer_from_address(link.get("link_name"))


# Hook this function to Address events via hooks.py
# doc_events = {
#     "Address": {
#         "on_update": "erpnext.stock.doctype.manufacturer.manufacturer.trigger_update_on_address_update"
#     }
# }
