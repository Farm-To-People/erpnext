# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
import json
from frappe.model.naming import set_name_by_naming_series
from frappe import _, msgprint
import frappe.defaults
from frappe.utils import flt, cint, cstr, today, get_formatted_email
from frappe.desk.reportview import build_match_conditions, get_filters_cond
from erpnext.utilities.transaction_base import TransactionBase
from erpnext import get_default_company
from erpnext.accounts.party import validate_party_accounts, get_dashboard_info, get_timeline_data # keep this
from frappe.contacts.address_and_contact import load_address_and_contact, delete_contact_and_address
from frappe.model.rename_doc import update_linked_doctypes
from frappe.model.mapper import get_mapped_doc
from frappe.utils.user import get_users_with_role

# Temporal
from temporal import any_to_date

class Customer(TransactionBase):
	def get_feed(self):
		return self.customer_name

	def onload(self):
		"""Load address and contacts in `__onload`"""
		load_address_and_contact(self)
		self.load_dashboard_info()

	def load_dashboard_info(self):
		info = get_dashboard_info(self.doctype, self.name, self.loyalty_program)
		self.set_onload('dashboard_info', info)

	def autoname(self):
		cust_master_name = frappe.defaults.get_global_default('cust_master_name')
		if cust_master_name == 'Customer Name':
			self.name = self.get_customer_name()
		else:
			set_name_by_naming_series(self)

	def get_customer_name(self):

		if frappe.db.get_value("Customer", self.customer_name) and not frappe.flags.in_import:
			count = frappe.db.sql("""select ifnull(MAX(CAST(SUBSTRING_INDEX(name, ' ', -1) AS UNSIGNED)), 0) from tabCustomer
				 where name like %s""", "%{0} - %".format(self.customer_name), as_list=1)[0][0]
			count = cint(count) + 1

			new_customer_name = "{0} - {1}".format(self.customer_name, cstr(count))

			msgprint(_("Changed customer name to '{}' as '{}' already exists.")
					.format(new_customer_name, self.customer_name),
					title=_("Note"), indicator="yellow")

			return new_customer_name

		return self.customer_name

	def after_insert(self):
		'''If customer created from Lead, update customer id in quotations, opportunities'''
		self.update_lead_status()

	def validate(self):
		self.flags.is_new_doc = self.is_new()
		self.flags.old_lead = self.lead_name
		validate_party_accounts(self)
		self.validate_credit_limit_on_change()
		self.set_loyalty_program()
		self.check_customer_group_change()
		self.validate_default_bank_account()
		self.validate_internal_customer()

		# set loyalty program tier
		if frappe.db.exists('Customer', self.name):
			customer = frappe.get_doc('Customer', self.name)
			if self.loyalty_program == customer.loyalty_program and not self.loyalty_program_tier:
				self.loyalty_program_tier = customer.loyalty_program_tier

		if self.sales_team:
			if sum(member.allocated_percentage or 0 for member in self.sales_team) != 100:
				frappe.throw(_("Total contribution percentage should be equal to 100"))

	@frappe.whitelist()
	def get_customer_group_details(self):
		doc = frappe.get_doc('Customer Group', self.customer_group)
		self.accounts = self.credit_limits = []
		self.payment_terms = self.default_price_list = ""

		tables = [["accounts", "account"], ["credit_limits", "credit_limit"]]
		fields = ["payment_terms", "default_price_list"]

		for row in tables:
			table, field = row[0], row[1]
			if not doc.get(table): continue

			for entry in doc.get(table):
				child = self.append(table)
				child.update({"company": entry.company, field: entry.get(field)})

		for field in fields:
			if not doc.get(field): continue
			self.update({field: doc.get(field)})

		self.save()

	def check_customer_group_change(self):
		frappe.flags.customer_group_changed = False

		if not self.get('__islocal'):
			if self.customer_group != frappe.db.get_value('Customer', self.name, 'customer_group'):
				frappe.flags.customer_group_changed = True

	def validate_default_bank_account(self):
		if self.default_bank_account:
			is_company_account = frappe.db.get_value('Bank Account', self.default_bank_account, 'is_company_account')
			if not is_company_account:
				frappe.throw(_("{0} is not a company bank account").format(frappe.bold(self.default_bank_account)))

	def validate_internal_customer(self):
		internal_customer = frappe.db.get_value("Customer",
			{"is_internal_customer": 1, "represents_company": self.represents_company, "name": ("!=", self.name)}, "name")

		if internal_customer:
			frappe.throw(_("Internal Customer for company {0} already exists").format(
				frappe.bold(self.represents_company)))

	def on_update(self):
		from ftp.ftp_module.doctype.customer_holds import customer_holds  # Important: Late Import due to Circular Reference

		self.validate_name_with_customer_group()
		self.create_primary_contact()
		self.create_primary_address()

		if self.flags.old_lead != self.lead_name:
			self.update_lead_status()

		if self.flags.is_new_doc:
			self.create_lead_address_contact()

		self.update_customer_groups()

		# Farm To People
		if self.customer_holds_changed():
			# If any Holds modified, update all related orders
			customer_holds._update_daily_orders(self.name)  # pylint: disable=protected-access

		# TODO: If value of opted_into_promotional_emails() changed, we need to do Mailchimp things.

	def update_customer_groups(self):
		ignore_doctypes = ["Lead", "Opportunity", "POS Profile", "Tax Rule", "Pricing Rule"]
		if frappe.flags.customer_group_changed:
			update_linked_doctypes('Customer', self.name, 'Customer Group',
				self.customer_group, ignore_doctypes)

	def create_primary_contact(self):
		if not self.customer_primary_contact and not self.lead_name:
			if self.mobile_no or self.email_id:
				contact = make_contact(self)
				self.db_set('customer_primary_contact', contact.name)
				self.db_set('mobile_no', self.mobile_no)
				# Farm To People - Disabling this so that email does not change.
				# self.db_set('email_id', self.email_id)

	def create_primary_address(self):
		if self.flags.is_new_doc and self.get('address_line1'):
			make_address(self)

	def update_lead_status(self):
		'''If Customer created from Lead, update lead status to "Converted"
		update Customer link in Quotation, Opportunity'''
		if self.lead_name:
			lead = frappe.get_doc('Lead', self.lead_name)
			lead.status = 'Converted'
			lead.save()

	def create_lead_address_contact(self):
		if self.lead_name:
			# assign lead address to customer (if already not set)
			address_names = frappe.get_all('Dynamic Link', filters={
								"parenttype":"Address",
								"link_doctype":"Lead",
								"link_name":self.lead_name
							}, fields=["parent as name"])

			for address_name in address_names:
				address = frappe.get_doc('Address', address_name.get('name'))
				if not address.has_link('Customer', self.name):
					address.append('links', dict(link_doctype='Customer', link_name=self.name))
					address.save(ignore_permissions=self.flags.ignore_permissions)

			lead = frappe.db.get_value("Lead", self.lead_name, ["organization_lead", "lead_name", "email_id", "phone", "mobile_no", "gender", "salutation"], as_dict=True)

			if not lead.lead_name:
				frappe.throw(_("Please mention the Lead Name in Lead {0}").format(self.lead_name))

			if lead.organization_lead:
				contact_names = frappe.get_all('Dynamic Link', filters={
									"parenttype":"Contact",
									"link_doctype":"Lead",
									"link_name":self.lead_name
								}, fields=["parent as name"])

				for contact_name in contact_names:
					contact = frappe.get_doc('Contact', contact_name.get('name'))
					if not contact.has_link('Customer', self.name):
						contact.append('links', dict(link_doctype='Customer', link_name=self.name))
						contact.save(ignore_permissions=self.flags.ignore_permissions)

			else:
				lead.lead_name = lead.lead_name.lstrip().split(" ")
				lead.first_name = lead.lead_name[0]
				lead.last_name = " ".join(lead.lead_name[1:])

				# create contact from lead
				contact = frappe.new_doc('Contact')
				contact.first_name = lead.first_name
				contact.last_name = lead.last_name
				contact.gender = lead.gender
				contact.salutation = lead.salutation
				contact.email_id = lead.email_id
				contact.phone = lead.phone
				contact.mobile_no = lead.mobile_no
				contact.is_primary_contact = 1
				contact.append('links', dict(link_doctype='Customer', link_name=self.name))
				if lead.email_id:
					contact.append('email_ids', dict(email_id=lead.email_id, is_primary=1))
				if lead.mobile_no:
					contact.append('phone_nos', dict(phone=lead.mobile_no, is_primary_mobile_no=1))
				contact.flags.ignore_permissions = self.flags.ignore_permissions
				contact.autoname()
				if not frappe.db.exists("Contact", contact.name):
					contact.insert()

	def validate_name_with_customer_group(self):
		if frappe.db.exists("Customer Group", self.name):
			frappe.throw(_("A Customer Group exists with same name please change the Customer name or rename the Customer Group"), frappe.NameError)

	def validate_credit_limit_on_change(self):
		if self.get("__islocal") or not self.credit_limits:
			return

		past_credit_limits = [d.credit_limit
			for d in frappe.db.get_all("Customer Credit Limit", filters={'parent': self.name}, fields=["credit_limit"], order_by="company")]

		current_credit_limits = [d.credit_limit for d in sorted(self.credit_limits, key=lambda k: k.company)]

		if past_credit_limits == current_credit_limits:
			return

		company_record = []
		for limit in self.credit_limits:
			if limit.company in company_record:
				frappe.throw(_("Credit limit is already defined for the Company {0}").format(limit.company, self.name))
			else:
				company_record.append(limit.company)

			outstanding_amt = get_customer_outstanding(self.name, limit.company)
			if flt(limit.credit_limit) < outstanding_amt:
				frappe.throw(_("""New credit limit is less than current outstanding amount for the customer. Credit limit has to be atleast {0}""").format(outstanding_amt))

	def on_trash(self):
		if self.customer_primary_contact:
			frappe.db.sql("""update `tabCustomer`
				set customer_primary_contact=null, mobile_no=null, email_id=null
				where name=%s""", self.name)

		delete_contact_and_address('Customer', self.name)
		if self.lead_name:
			frappe.db.sql("update `tabLead` set status='Interested' where name=%s", self.lead_name)

	def after_rename(self, olddn, newdn, merge=False):
		if frappe.defaults.get_global_default('cust_master_name') == 'Customer Name':
			frappe.db.set(self, "customer_name", newdn)

	def set_loyalty_program(self):
		if self.loyalty_program:
			return

		loyalty_program = get_loyalty_programs(self)
		if not loyalty_program:
			return

		if len(loyalty_program) == 1:
			self.loyalty_program = loyalty_program[0]
		else:
			frappe.msgprint(
				_("Multiple Loyalty Programs found for Customer {}. Please select manually.")
				.format(frappe.bold(self.customer_name))
			)

	def create_onboarding_docs(self, args):
		defaults = frappe.defaults.get_defaults()
		company = defaults.get('company') or \
			frappe.db.get_single_value('Global Defaults', 'default_company')

		for i in range(1, args.get('max_count')):
			customer = args.get('customer_name_' + str(i))
			if customer:
				try:
					doc = frappe.get_doc({
						'doctype': self.doctype,
						'customer_name': customer,
						'customer_type': 'Company',
						'customer_group': _('Commercial'),
						'territory': defaults.get('country'),
						'company': company
					}).insert()

					if args.get('customer_email_' + str(i)):
						create_contact(customer, self.doctype,
							doc.name, args.get("customer_email_" + str(i)))
				except frappe.NameError:
					pass


def create_contact(contact, party_type, party, email):
	"""Create contact based on given contact name"""
	contact = contact.split(' ')

	contact = frappe.get_doc({
		'doctype': 'Contact',
		'first_name': contact[0],
		'last_name': len(contact) > 1 and contact[1] or ""
	})
	contact.append('email_ids', dict(email_id=email, is_primary=1))
	contact.append('links', dict(link_doctype=party_type, link_name=party))
	contact.insert()

@frappe.whitelist()
def make_quotation(source_name, target_doc=None):

	def set_missing_values(source, target):
		_set_missing_values(source, target)

	target_doc = get_mapped_doc("Customer", source_name,
		{"Customer": {
			"doctype": "Quotation",
			"field_map": {
				"name":"party_name"
			}
		}}, target_doc, set_missing_values)

	target_doc.quotation_to = "Customer"
	target_doc.run_method("set_missing_values")
	target_doc.run_method("set_other_charges")
	target_doc.run_method("calculate_taxes_and_totals")

	price_list, currency = frappe.db.get_value("Customer", {'name': source_name}, ['default_price_list', 'default_currency'])
	if price_list:
		target_doc.selling_price_list = price_list
	if currency:
		target_doc.currency = currency

	return target_doc

@frappe.whitelist()
def make_opportunity(source_name, target_doc=None):
	def set_missing_values(source, target):
		_set_missing_values(source, target)

	target_doc = get_mapped_doc("Customer", source_name,
		{"Customer": {
			"doctype": "Opportunity",
			"field_map": {
				"name": "party_name",
				"doctype": "opportunity_from",
			}
		}}, target_doc, set_missing_values)

	return target_doc

def _set_missing_values(source, target):
	address = frappe.get_all('Dynamic Link', {
			'link_doctype': source.doctype,
			'link_name': source.name,
			'parenttype': 'Address',
		}, ['parent'], limit=1)

	contact = frappe.get_all('Dynamic Link', {
			'link_doctype': source.doctype,
			'link_name': source.name,
			'parenttype': 'Contact',
		}, ['parent'], limit=1)

	if address:
		target.customer_address = address[0].parent

	if contact:
		target.contact_person = contact[0].parent

@frappe.whitelist()
def get_loyalty_programs(doc):
	''' returns applicable loyalty programs for a customer '''

	lp_details = []
	loyalty_programs = frappe.get_all("Loyalty Program",
		fields=["name", "customer_group", "customer_territory"],
		filters={"auto_opt_in": 1, "from_date": ["<=", today()],
			"ifnull(to_date, '2500-01-01')": [">=", today()]})

	for loyalty_program in loyalty_programs:
		if (
			(not loyalty_program.customer_group
			or doc.customer_group in get_nested_links(
				"Customer Group",
				loyalty_program.customer_group,
				doc.flags.ignore_permissions
			))
			and (not loyalty_program.customer_territory
			or doc.territory in get_nested_links(
				"Territory",
				loyalty_program.customer_territory,
				doc.flags.ignore_permissions
			))
		):
			lp_details.append(loyalty_program.name)

	return lp_details

def get_nested_links(link_doctype, link_name, ignore_permissions=False):
	from frappe.desk.treeview import _get_children

	links = [link_name]
	for d in _get_children(link_doctype, link_name, ignore_permissions):
		links.append(d.value)

	return links

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_customer_list(doctype, txt, searchfield, start, page_len, filters=None):
	from erpnext.controllers.queries import get_fields
	fields = ["name", "customer_name", "customer_group", "territory"]

	if frappe.db.get_default("cust_master_name") == "Customer Name":
		fields = ["name", "customer_group", "territory"]

	fields = get_fields("Customer", fields)

	match_conditions = build_match_conditions("Customer")
	match_conditions = "and {}".format(match_conditions) if match_conditions else ""

	if filters:
		filter_conditions = get_filters_cond(doctype, filters, [])
		match_conditions += "{}".format(filter_conditions)

	return frappe.db.sql("""
		select %s
		from `tabCustomer`
		where docstatus < 2
			and (%s like %s or customer_name like %s)
			{match_conditions}
		order by
			case when name like %s then 0 else 1 end,
			case when customer_name like %s then 0 else 1 end,
			name, customer_name limit %s, %s
		""".format(match_conditions=match_conditions) % (", ".join(fields), searchfield, "%s", "%s", "%s", "%s", "%s", "%s"),
		("%%%s%%" % txt, "%%%s%%" % txt, "%%%s%%" % txt, "%%%s%%" % txt, start, page_len))


def check_credit_limit(customer, company, ignore_outstanding_sales_order=False, extra_amount=0):
	customer_outstanding = get_customer_outstanding(customer, company, ignore_outstanding_sales_order)
	if extra_amount > 0:
		customer_outstanding += flt(extra_amount)

	credit_limit = get_credit_limit(customer, company)
	if credit_limit > 0 and flt(customer_outstanding) > credit_limit:
		msgprint(_("Credit limit has been crossed for customer {0} ({1}/{2})")
			.format(customer, customer_outstanding, credit_limit))

		# If not authorized person raise exception
		credit_controller_role = frappe.db.get_single_value('Accounts Settings', 'credit_controller')
		if not credit_controller_role or credit_controller_role not in frappe.get_roles():
			# form a list of emails for the credit controller users
			credit_controller_users = get_users_with_role(credit_controller_role or "Sales Master Manager")

			# form a list of emails and names to show to the user
			credit_controller_users_formatted = [get_formatted_email(user).replace("<", "(").replace(">", ")") for user in credit_controller_users]
			if not credit_controller_users_formatted:
				frappe.throw(_("Please contact your administrator to extend the credit limits for {0}.").format(customer))

			message = """Please contact any of the following users to extend the credit limits for {0}:
				<br><br><ul><li>{1}</li></ul>""".format(customer, '<li>'.join(credit_controller_users_formatted))

			# if the current user does not have permissions to override credit limit,
			# prompt them to send out an email to the controller users
			frappe.msgprint(message,
				title="Notify",
				raise_exception=1,
				primary_action={
					'label': 'Send Email',
					'server_action': 'erpnext.selling.doctype.customer.customer.send_emails',
					'args': {
						'customer': customer,
						'customer_outstanding': customer_outstanding,
						'credit_limit': credit_limit,
						'credit_controller_users_list': credit_controller_users
					}
				}
			)

@frappe.whitelist()
def send_emails(args):
	args = json.loads(args)
	subject = (_("Credit limit reached for customer {0}").format(args.get('customer')))
	message = (_("Credit limit has been crossed for customer {0} ({1}/{2})")
			.format(args.get('customer'), args.get('customer_outstanding'), args.get('credit_limit')))
	frappe.sendmail(recipients=args.get('credit_controller_users_list'), subject=subject, message=message)

def get_customer_outstanding(customer, company, ignore_outstanding_sales_order=False, cost_center=None):
	# Outstanding based on GL Entries

	cond = ""
	if cost_center:
		lft, rgt = frappe.get_cached_value("Cost Center",
			cost_center, ['lft', 'rgt'])

		cond = """ and cost_center in (select name from `tabCost Center` where
			lft >= {0} and rgt <= {1})""".format(lft, rgt)

	outstanding_based_on_gle = frappe.db.sql("""
		select sum(debit) - sum(credit)
		from `tabGL Entry` where party_type = 'Customer'
		and party = %s and company=%s {0}""".format(cond), (customer, company))

	outstanding_based_on_gle = flt(outstanding_based_on_gle[0][0]) if outstanding_based_on_gle else 0

	# Outstanding based on Sales Order
	outstanding_based_on_so = 0

	# if credit limit check is bypassed at sales order level,
	# we should not consider outstanding Sales Orders, when customer credit balance report is run
	if not ignore_outstanding_sales_order:
		outstanding_based_on_so = frappe.db.sql("""
			select sum(base_grand_total*(100 - per_billed)/100)
			from `tabSales Order`
			where customer=%s and docstatus = 1 and company=%s
			and per_billed < 100 and status != 'Closed'""", (customer, company))

		outstanding_based_on_so = flt(outstanding_based_on_so[0][0]) if outstanding_based_on_so else 0

	# Outstanding based on Delivery Note, which are not created against Sales Order
	outstanding_based_on_dn = 0

	unmarked_delivery_note_items = frappe.db.sql("""select
			dn_item.name, dn_item.amount, dn.base_net_total, dn.base_grand_total
		from `tabDelivery Note` dn, `tabDelivery Note Item` dn_item
		where
			dn.name = dn_item.parent
			and dn.customer=%s and dn.company=%s
			and dn.docstatus = 1 and dn.status not in ('Closed', 'Stopped')
			and ifnull(dn_item.against_sales_order, '') = ''
			and ifnull(dn_item.against_sales_invoice, '') = ''
		""", (customer, company), as_dict=True)

	if not unmarked_delivery_note_items:
		return outstanding_based_on_gle + outstanding_based_on_so

	si_amounts = frappe.db.sql("""
		SELECT
			dn_detail, sum(amount) from `tabSales Invoice Item`
		WHERE
			docstatus = 1
			and dn_detail in ({})
		GROUP BY dn_detail""".format(", ".join(
			frappe.db.escape(dn_item.name)
			for dn_item in unmarked_delivery_note_items
		))
	)

	si_amounts = {si_item[0]: si_item[1] for si_item in si_amounts}

	for dn_item in unmarked_delivery_note_items:
		dn_amount = flt(dn_item.amount)
		si_amount = flt(si_amounts.get(dn_item.name))

		if dn_amount > si_amount and dn_item.base_net_total:
			outstanding_based_on_dn += ((dn_amount - si_amount)
				/ dn_item.base_net_total) * dn_item.base_grand_total

	return outstanding_based_on_gle + outstanding_based_on_so + outstanding_based_on_dn


def get_credit_limit(customer, company):
	credit_limit = None

	if customer:
		credit_limit = frappe.db.get_value("Customer Credit Limit",
			{'parent': customer, 'parenttype': 'Customer', 'company': company}, 'credit_limit')

		if not credit_limit:
			customer_group = frappe.get_cached_value("Customer", customer, 'customer_group')
			credit_limit = frappe.db.get_value("Customer Credit Limit",
				{'parent': customer_group, 'parenttype': 'Customer Group', 'company': company}, 'credit_limit')

	if not credit_limit:
		credit_limit = frappe.get_cached_value('Company',  company,  "credit_limit")

	return flt(credit_limit)

def make_contact(args, is_primary_contact=1):
	contact = frappe.get_doc({
		'doctype': 'Contact',
		'first_name': args.get('name'),
		'is_primary_contact': is_primary_contact,
		'links': [{
			'link_doctype': args.get('doctype'),
			'link_name': args.get('name')
		}]
	})
	if args.get('email_id'):
		contact.add_email(args.get('email_id'), is_primary=True)
	if args.get('mobile_no'):
		contact.add_phone(args.get('mobile_no'), is_primary_mobile_no=True)
	contact.insert()

	return contact

def make_address(args, is_primary_address=1):
	reqd_fields = []
	for field in ['city', 'country']:
		if not args.get(field):
			reqd_fields.append( '<li>' + field.title() + '</li>')

	if reqd_fields:
		msg = _("Following fields are mandatory to create address:")
		frappe.throw("{0} <br><br> <ul>{1}</ul>".format(msg, '\n'.join(reqd_fields)),
			title = _("Missing Values Required"))

	address = frappe.get_doc({
		'doctype': 'Address',
		'address_title': args.get('name'),
		'address_line1': args.get('address_line1'),
		'address_line2': args.get('address_line2'),
		'city': args.get('city'),
		'state': args.get('state'),
		'pincode': args.get('pincode'),
		'country': args.get('country'),
		'links': [{
			'link_doctype': args.get('doctype'),
			'link_name': args.get('name')
		}]
	}).insert()

	return address

# NOTE: Datahenge: This Frappe script looks incorrect.  Doesn't even filter on Boolean 'is_primary_contact'
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_customer_primary_contact(doctype, txt, searchfield, start, page_len, filters):
	customer = filters.get('customer')
	return frappe.db.sql("""
		select `tabContact`.name from `tabContact`, `tabDynamic Link`
			where `tabContact`.name = `tabDynamic Link`.parent and `tabDynamic Link`.link_name = %(customer)s
			and `tabDynamic Link`.link_doctype = 'Customer'
			and `tabContact`.name like %(txt)s
		""", {
			'customer': customer,
			'txt': '%%%s%%' % txt
		})

# Datahenge: Adding here, so we can reference in Class refactoring below
def get_ar_balance_per_customer_per_gl(customer_key, validate_exists=False):
	"""
	Get a simple AR balance based on General Ledger transactions.
	"""

	if validate_exists and (not frappe.db.exists("Customer", customer_key)):
		frappe.throw(f"Cannot find Customer with 'name' = '{customer_key}'")

	company = get_default_company()
	outstanding_based_on_gle = frappe.db.sql("""
		select sum(debit) - sum(credit)
		from `tabGL Entry` where party_type = 'Customer'
		and party = %s and company=%s""", (customer_key, company))

	balance = flt(outstanding_based_on_gle[0][0]) if outstanding_based_on_gle else 0.00
	return balance


@frappe.whitelist()
def get_customer_phone_number(customer_key):
	"""
	Get a customer's Phone Number from their Primary Contact.
	"""

	query = """SELECT `tabContact`.phone
		FROM `tabContact`
		INNER JOIN `tabDynamic Link`
		ON `tabDynamic Link`.parent = `tabContact`.name
		AND `tabDynamic Link`.link_doctype = 'Customer'
		AND `tabDynamic Link`.link_name = %(customer_key)s
		WHERE `tabContact`.is_primary_contact = 1
		"""

	result = frappe.db.sql(query, values={"customer_key": customer_key})
	if (not result) or (not result[0]):
		return None

	return result[0][0]

def is_customer_anon(customer_key_or_doc):
	"""
	Return a boolean indicating if Customer is anonymous, or not.
	"""
	if isinstance(customer_key_or_doc, str):
		customer_key = frappe.db.get_value('Customer',  customer_key_or_doc,  'name')
		return bool(customer_key.startswith('anon'))

	return bool(customer_key_or_doc.name.startswith('anon'))


class Customer(Customer):  # pylint: disable=function-redefined

	# Datahenge:  This is kind of nonsense, extending a class from itself.
	# However, it's a rather nice technique for extend the standard Customer Class without
	# intermingles the code above, which does make Git Diff more difficult to reconcile.

	def on_change(self):
		# FTP: If customer's name changed, then update Web Subscription names
		# Datahenge: This is why 1) We shouldn't store DocType attributes in secondary tables.
		#            And also 2) Why ERPNext really needs the concept of 'Display Methods'
		if self.has_value_changed('customer_name'):
			statement = """ UPDATE `tabWeb Subscription`
			SET customer_name = %(customer_name)s
			WHERE customer = %(customer_id)s
			"""
			frappe.db.sql(statement, values={"customer_name": self.customer_name, "customer_id": self.name } )

	def before_insert(self):
		if not self.referral_code:
			self.set_referral_code()

	def before_validate(self):
		if not self.referral_code:
			self.set_referral_code()

	def after_insert(self):
		from ftp.utilities.mandrill import send_welcome_to_ftp
		super().after_insert()
		if not self.is_anon():
			send_welcome_to_ftp(self.name)  # Farm to People + Mandrill welcome email via Redis Queue.


	def on_update(self):
		# Note: Parent's update may (or may not) have involved some CRUD on Child Tables.
		super().on_update()
		self.on_update_children(child_docfield_name='pauses')

	@staticmethod
	def get_customer_by_emailid(email_address, err_on_missing=False):
		"""
		Find a Customer based on email address.
		"""
		customers = frappe.db.get_all("Customer", filters=[ {"email_id": email_address} ], pluck='name')
		# Rule: There Can Only Be One
		if len(customers) == 0:
			if err_on_missing:
				frappe.throw(_(f"No customer found with email address = '{email_address}'"))
			return None
		if len(customers) > 1:
			frappe.throw(_(f"Unexpected Error: More than 1 customer found with email address '{email_address}'"))

		customer = frappe.get_doc("Customer", customers[0])
		return customer

	def is_anon(self):
		"""
		Returns a boolean if customer is anonymous.
		"""
		return is_customer_anon(self)


	def get_ar_balance_per_gl(self):
		"""
		Get a simple AR balance based on General Ledger transactions.
		"""
		return get_ar_balance_per_customer_per_gl(self.name)

	def get_ar_journal_credits(self, debug=False):
		"""
			Return information about AR Credits that were issued via Journal Entries.
		"""
		query = """
			SELECT JournalHeader.name, JournalHeader.docstatus, voucher_type, debit - credit AS AR_Adjustment 
			FROM `tabJournal Entry Account`		AS JournalLine
			JOIN `tabJournal Entry`		AS JournalHeader
			ON	JournalHeader.name = JournalLine.parent
			AND JournalHeader.docstatus = 1   -- posted
			WHERE JournalLine.account_type = 'Receivable'
			AND   JournalLine.party_type = 'Customer'
			AND   JournalLine.party = %(customer_key)s
		"""
		result = frappe.db.sql(query=query,
		                       values={"customer_key": self.name},
							   as_dict=True, debug=debug, explain=debug)
		return result

	def _get_open_ar_transactions(self, debug=False):
		"""
			Get a list of Invoices and Payments that are open.

			Returns:  List of Dictionary.
			Note: Does not include any Journal Entries that target Accounts Receivable directly.
		"""

		query = """
		SELECT
			'Payment Entry' as transaction_type, name, party, payment_type, posting_date, paid_amount, unallocated_amount, reference_no
		FROM
			`tabPayment Entry`
		WHERE
			party_type = 'Customer'
		AND unallocated_amount <> 0
		AND docstatus = 1
		AND party = %(customer_key)s

		UNION ALL

		SELECT
			'Invoice' as transaction_type, name, customer, status, posting_date, grand_total, outstanding_amount, ''
		FROM 
			`tabSales Invoice`
		WHERE
			outstanding_amount <> 0
		AND docstatus = 1
		AND customer =  %(customer_key)s
		"""
		result = frappe.db.sql(query=query,
		                       values={"customer_key": self.name},
							   as_dict=True, debug=debug, explain=debug)
		return result

	def get_ar_balance_per_transactions(self):
		from ftp.ftp_module.generics import value_to_currency  # deliberate late import, because it's cross-module

		transactions = self._get_open_ar_transactions()
		balance = value_to_currency(0.00)
		for row in transactions:
			if row['transaction_type'] == 'Payment Entry':
				balance -= value_to_currency(row['unallocated_amount'])
			else:
				balance += value_to_currency(row['unallocated_amount'])
		return balance

	@frappe.whitelist()
	def show_accounts_receivable_summary(self):
		"""
		Return a lightly formatted message, showing a Customer's AR Balance.
		This message does --not-- include a breakdown about Credit Allocations to Daily Orders.
		"""
		message = f"Accounts Receivable Summary for Customer: {self.name}\n"
		message += f"\n\u2022 AR Balance per GL: {self.get_ar_balance_per_gl()}"
		message += f"\n\u2022 AR Balance per Transactions: {self.get_ar_balance_per_transactions()}"
		message = message.replace("\n","<br>")
		return message

	def customer_holds_changed(self):
		"""
		Try to determine if the Customer Holds child table was modified.
		"""
		holds_orig = None
		if hasattr(self, '_doc_before_save'):
			if self._doc_before_save:
				holds_orig = self._doc_before_save.pauses
		holds_current = self.pauses

		if (not holds_orig) and (not holds_current):  # no pauses exist
			return False
		if holds_orig and not holds_current:  # rows deleted
			return True
		if not holds_orig and holds_current:  # rows added
			return True
		if len(holds_orig) != len(holds_current):  # rowcount changed
			return True

		for idx, row in enumerate(holds_current):
			# I really, REALLY dislike how -inconsistent- date fields are in Frappe framework.
			if any_to_date(row.from_date) != any_to_date(holds_orig[idx].from_date):
				return True
			if any_to_date(row.to_date) != any_to_date(holds_orig[idx].to_date):
				return True
		return False

	# Farm To People
	@frappe.whitelist()
	def collect_daily_order_payments(self):
		from ftp.ftp_module.payments import PaymentProcessor
		PaymentProcessor(disable_prechecks=True).pay_all_by_customer(self)

	@frappe.whitelist()
	def set_referral_code(self, force_save=False):
		"""
		Generate and set a new referral code for this Customer.
		"""
		from ftp.utilities.referral_code import generate_code
		self.referral_code = generate_code()

		if force_save:
			# Typically used when called from JavaScript, to force an immediate save on the Customer record.
			self.save()
		return self.referral_code  # used by JS callback.
