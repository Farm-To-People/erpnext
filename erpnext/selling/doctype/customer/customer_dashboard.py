from __future__ import unicode_literals

from frappe import _

# Farm To People: Removing some unused Connection links.
def get_data():
	return {
		'heatmap': True,
		'heatmap_message': _('This is based on transactions against this Customer. See timeline below for details'),
		'fieldname': 'customer',
		'non_standard_fieldnames': {
			'Payment Entry': 'party',
			'Quotation': 'party_name',
			'Opportunity': 'party_name',
			'Bank Account': 'party',
			'Subscription': 'party',
			'Item Favorites': 'customer_key'
		},
		'dynamic_links': {
			'party_name': ['Customer', 'quotation_to']
		},
		'transactions': [
			#{
			#	'label': _('Pre Sales'),
			#	'items': ['Opportunity', 'Quotation']
			#},
			{
				'label': _('Website'),
				'items': ['Auth User', 'Item Favorites']
			},
			{
				'label': _('Orders'),
				'items': ['Daily Order', 'Sales Order', 'Delivery Note', 'Sales Invoice']
			},
			{
				'label': _('Payments'),
				'items': ['Payment Entry', 'Bank Account']
			},
			#{
			#	'label': _('Support'),
			#	'items': ['Issue', 'Maintenance Visit', 'Installation Note', 'Warranty Claim']
			#},
			#{
			#	'label': _('Projects'),
			#	'items': ['Project']
			#},
			{
				'label': _('Pricing'),
				'items': ['Pricing Rule']
			},
			{
				'label': _('Web Subscriptions'),
				'items': ['Web Subscription']
			}
		]
	}
