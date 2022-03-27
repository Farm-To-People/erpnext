
-- AR Summary by Type

SELECT
	'Payment Entry'		AS transaction_type,
	-SUM(paid_amount)	AS amount
FROM
	`tabPayment Entry`
WHERE
	party_type = 'Customer'
AND docstatus = 1
AND party = %(customer_key)s

UNION ALL

SELECT
	'Invoices' as transaction_type,
	SUM(grand_total)	AS amount
FROM 
	`tabSales Invoice`
WHERE
  	docstatus = 1
AND customer =  %(customer_key)s
AND grand_total >=0 

UNION ALL

SELECT
	'Credit Notes' as transaction_type, SUM(grand_total)	AS amount
FROM 
	`tabSales Invoice`
WHERE
  	docstatus = 1
AND customer =  %(customer_key)s
AND grand_total < 0 

UNION ALL

SELECT
	'Journal Entries' as transaction_type, SUM(debit - credit)	AS amount
FROM 
	`tabJournal Entry Account`	AS JournalEntryLine
WHERE
	docstatus = 1
AND account = 'Debtors - FTP'
AND party = %(customer_key)s


