
# Datahenge: Including the Customer on the dashboard
def get_data():
	return {
		"fieldname": "lead",
		"non_standard_fieldnames": {"Customer": "lead_name", "Quotation": "party_name", "Opportunity": "party_name"},
		"dynamic_links": {"party_name": ["Lead", "quotation_to"]},
		"transactions": [
			{"items": ["Opportunity", "Quotation", "Prospect", "Customer"]},
		],
	}
