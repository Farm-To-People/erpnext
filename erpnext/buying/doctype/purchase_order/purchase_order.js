// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.buying");
frappe.provide("erpnext.accounts.dimensions");
{% include 'erpnext/public/js/controllers/buying.js' %};

frappe.ui.form.on("Purchase Order", {
	setup: function(frm) {

		frm.set_query("reserve_warehouse", "supplied_items", function() {
			return {
				filters: {
					"company": frm.doc.company,
					"name": ['!=', frm.doc.supplier_warehouse],
					"is_group": 0
				}
			}
		});

		frm.set_indicator_formatter('item_code',
			function(doc) { return (doc.qty<=doc.received_qty) ? "green" : "orange" })

		frm.set_query("expense_account", "items", function() {
			return {
				query: "erpnext.controllers.queries.get_expense_account",
				filters: {'company': frm.doc.company}
			}
		});

		set_target_warehouse(frm);  // Farm To People
	},

	company: function(frm) {
		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
	},

	onload: function(frm) {
		set_schedule_date(frm);
		if (!frm.doc.transaction_date){
			frm.set_value('transaction_date', frappe.datetime.get_today())
		}

		erpnext.queries.setup_queries(frm, "Warehouse", function() {
			return erpnext.queries.warehouse(frm.doc);
		});

		erpnext.accounts.dimensions.setup_dimension_filters(frm, frm.doctype);

		// Farm To People
		//if (!frm.doc.supplier) {
		//	console.log("Setting focus on Supplier field...");
		//	frm.get_field('supplier').$input.focus();
		//}
	},

	apply_tds: function(frm) {
		if (!frm.doc.apply_tds) {
			frm.set_value("tax_withholding_category", '');
		} else {
			frm.set_value("tax_withholding_category", frm.supplier_tds);
		}
	},

	refresh: function(frm) {
		frm.trigger('get_materials_from_supplier');  // Datahenge: This is the Standard ERPNext function, not the Farm to People function.

		/* FTP: Hide the standard Submit Button: */
		// $('.primary-action').prop('hidden', true);

		if (!frm.doc.__unsaved && frm.doc.docstatus == 0 && frm.doc.status != "Closed") {

			// Custom Submit button #2
			frm.add_custom_button(__('Email'),

				function() {
					frappe.db.get_value("Supplier", {"name": frm.doc.supplier}, "emails_for_purchase_order").then(val => {

						let recipients = val.message.emails_for_purchase_order;
						new frappe.views.CommunicationComposer({
							doc: frm.doc,
							frm: frm,
							subject: __(frm.meta.name) + ': ' + frm.docname,
							recipients: recipients,
							attach_document_print: true,
							message: "Purchase Order from Farm To People:",
							real_name: frm.doc.real_name || frm.doc.contact_display || frm.doc.contact_name
						});
					});
				}
			);

			if (frm.doc.supplier) {
				/* FTP: Add 'Supplier' to 'Get Items From'
				   Result is 1 PO line for each Item with a matching Default Supplier.
				*/
				frm.add_custom_button(__('Supplier'), () => {
					frappe.call({
						method: "erpnext.buying.doctype.purchase_order.purchase_order.get_suppliers_default_items",
						args: { "supplier_id": frm.doc.supplier},
						callback: function(r) {
							if (r.message) {
								frappe.msgprint(__("Added new PO lines; please update Quantity and Rates."));
								let possible_new_lines = r.message;  // array of objects from the Python function
								possible_new_lines.forEach(function (row, index) {

									// console.log(row);

									// Does this row already exist?
									let existing_rows = frm.doc.items;
									console.log(existing_rows);

									// Create a new Purchase Order Line:
									var new_order_line = cur_frm.add_child("items");
									new_order_line.item_code = row['item_code'];
									new_order_line.uom = row['purchase_uom'];
									new_order_line.item_name = row['item_name'];
									new_order_line.rate = row['price_list_rate'];
									new_order_line.price_list_rate = new_order_line.rate;
									// "Base" Rates are the Company Currency Rates
									new_order_line.base_rate = new_order_line.rate;
									new_order_line.base_price_list_rate = new_order_line.price_list_rate;
									new_order_line.conversion_factor = row['conversion_factor']
									new_order_line.schedule_date = frm.doc.schedule_date;
									cur_frm.refresh_fields("items");  // Important to refresh that portion of the page!
								});
							}
						}
					});
				}, __("Get Items From"));

				// FTP: Add lines based on Daily Order's where this is the default Supplier of the Item.
				frm.add_custom_button(__('Daily Orders'), 
				                      () => frm.trigger('create_lines_from_daily_orders'),
									  __("Get Items From"));
			}
		}  // end of if docstatus == 0

		// FTP: Add the ability to reverse a Submit.
		if (frm.doc.docstatus == 1) {

			cur_frm.set_df_property("Submit", "hidden", true);  // Try to hide the custom Submit button.

			frm.add_custom_button(__('Reverse Submit'), () => {
				frappe.call({
					method: "reverse_submit_ftp",
					doc: frm.doc,
					callback: function(r) {
						if (r.message) {
							frappe.msgprint(__("{0}", [r.message]));
						}
						frm.reload_doc();  // Because the docstatus changed.
					}
				});
			}, __("Status"));
		}

	// end of refresh()
	},

	get_materials_from_supplier: function(frm) {
		/*
			Datahenge: WARNING, the code below is an Out-Of-The-Box function. 
			           It's used as part of Raw Material subcontracting with a Supplier.
				       It is --not-- the same as FTP's function that gets all Item Codes who have a default Supplier.
					   See instead: get_suppliers_default_items()
		*/
		let po_details = [];

		if (frm.doc.supplied_items && (frm.doc.per_received == 100 || frm.doc.status === 'Closed')) {
			frm.doc.supplied_items.forEach(d => {
				if (d.total_supplied_qty && d.total_supplied_qty != d.consumed_qty) {
					po_details.push(d.name)
				}
			});
		}

		if (po_details && po_details.length) {
			frm.add_custom_button(__('Return of Components'), () => {
				frm.call({
					method: 'erpnext.buying.doctype.purchase_order.purchase_order.get_materials_from_supplier',
					freeze: true,
					freeze_message: __('Creating Stock Entry'),
					args: { purchase_order: frm.doc.name, po_details: po_details },
					callback: function(r) {
						if (r && r.message) {
							const doc = frappe.model.sync(r.message);
							frappe.set_route("Form", doc[0].doctype, doc[0].name);
						}
					}
				});
			}, __('Create'));
		}
	},

	create_lines_from_daily_orders: function(frm) {

		// First, open a Dialog Box with a date range.
		let mydialog = new frappe.ui.Dialog({
			title: __('Add PO lines based on Daily Orders'),
			fields: [
				{
					"fieldname": "delivery_date_from",
					"label" : __("Date From"),
					"fieldtype": "Date",
					"reqd": 1,
				},
				{
					"fieldname": "delivery_date_to",
					"label" : __("Date To"),
					"fieldtype": "Date",
					"reqd": 1,
				}
			],
			primary_action: function() {
				let dialog_args = mydialog.get_values();

				frappe.call({
					method: "erpnext.buying.doctype.purchase_order.purchase_order.get_purchase_lines_based_on_sales",
					args: {
						supplier_id: frm.doc.supplier,
						delivery_date_from: dialog_args.delivery_date_from,
						delivery_date_to: dialog_args.delivery_date_to
					},
					callback: function(r) {
						if (r.message) {
							let number_of_rows = r.message.length;
							r.message.forEach(row => {
								// Create a new Purchase Order Line:
								let new_order_line = frm.add_child("items");
								new_order_line.item_code = row['item_code'];
								new_order_line.item_name = row['item_name'];
								new_order_line.uom = row['uom'];
								new_order_line.qty = row['quantity'];
								new_order_line.rate = row['price_list_rate'];
								new_order_line.price_list_rate = new_order_line.rate;
								new_order_line.amount = new_order_line.qty * new_order_line.rate;
								// "Base" Rates are the Company Currency Rates
								new_order_line.base_rate = new_order_line.rate;
								new_order_line.base_price_list_rate = new_order_line.price_list_rate;
								new_order_line.base_amount = new_order_line.amount;

								new_order_line.conversion_factor = 1;
								new_order_line.schedule_date = frm.doc.schedule_date;
							});
							frm.refresh_fields("items");  // Important to refresh that portion of the page!
							// frm.save();   // Do not save, per conversation with Shelby on 15th of April.
							frappe.msgprint(__("Added {0} new lines to the Purchase Order.", [number_of_rows]));
							mydialog.hide();						
						}
					}
				});
			},
			primary_action_label: __('Add')
		});
		mydialog.show();
	}

	,schedule_date: function(frm) {
		// Farm To People: Update the "Stock Use Date" whenever the Order Confirmation Date is updated.
		frappe.db.get_single_value("Buying Settings", "stock_use_days_offset").then(val => {
			let new_stock_use_date = frappe.datetime.add_days(frm.doc.schedule_date, val);
			frm.set_value("stock_use_date", new_stock_use_date );
		})
	}

});

frappe.ui.form.on("Purchase Order Item", {

	schedule_date: function(frm, cdt, cdn) {

		/*
			Farm To People: Adding a means of prioritizing Order Header's schedule_date, over Lines.
		*/
		frappe.db.get_single_value("Buying Settings", "use_header_required_by").then(val => {

			if (val == 1) {
				return;
			}

			var row = locals[cdt][cdn];
			if (row.schedule_date) {
				if(!frm.doc.schedule_date) {
					erpnext.utils.copy_value_in_all_rows(frm.doc, cdt, cdn, "items", "schedule_date");
				} else {
					set_schedule_date(frm);
				}
			}
		});

	} // end schedule_date

});

erpnext.buying.PurchaseOrderController = erpnext.buying.BuyingController.extend({
	setup: function() {
		this.frm.custom_make_buttons = {
			'Purchase Receipt': 'Purchase Receipt',
			'Purchase Invoice': 'Purchase Invoice',
			'Stock Entry': 'Material to Supplier',
			'Payment Entry': 'Payment',
		}

		this._super();

	},

	refresh: function(doc, cdt, cdn) {
		var me = this;
		this._super();
		var allow_receipt = false;
		var is_drop_ship = false;

		for (var i in cur_frm.doc.items) {
			var item = cur_frm.doc.items[i];
			if(item.delivered_by_supplier !== 1) {
				allow_receipt = true;
			} else {
				is_drop_ship = true;
			}

			if(is_drop_ship && allow_receipt) {
				break;
			}
		}

		this.frm.set_df_property("drop_ship", "hidden", !is_drop_ship);

		if(doc.docstatus == 1) {
			this.frm.fields_dict.items_section.wrapper.addClass("hide-border");
			if(!this.frm.doc.set_warehouse) {
				this.frm.fields_dict.items_section.wrapper.removeClass("hide-border");
			}

			if(!in_list(["Closed", "Delivered"], doc.status)) {
				if(this.frm.doc.status !== 'Closed' && flt(this.frm.doc.per_received) < 100 && flt(this.frm.doc.per_billed) < 100) {
					this.frm.add_custom_button(__('Update Items'), () => {
						erpnext.utils.update_child_items({
							frm: this.frm,
							child_docname: "items",
							child_doctype: "Purchase Order Detail",
							cannot_add_row: true,  // Farm To People request
							cannot_delete_row: true  // Farm To People request
						})
					});
				}
				if (this.frm.has_perm("submit")) {
					if(flt(doc.per_billed, 6) < 100 || flt(doc.per_received, 6) < 100) {
						if (doc.status != "On Hold") {
							this.frm.add_custom_button(__('Hold'), () => this.hold_purchase_order(), __("Status"));
						} else{
							this.frm.add_custom_button(__('Resume'), () => this.unhold_purchase_order(), __("Status"));
						}
						this.frm.add_custom_button(__('Close'), () => this.close_purchase_order(), __("Status"));
					}
				}

				if(is_drop_ship && doc.status!="Delivered") {
					this.frm.add_custom_button(__('Delivered'),
						this.delivered_by_supplier, __("Status"));

					this.frm.page.set_inner_btn_group_as_primary(__("Status"));
				}
			} else if(in_list(["Closed", "Delivered"], doc.status)) {
				if (this.frm.has_perm("submit")) {
					this.frm.add_custom_button(__('Re-open'), () => this.unclose_purchase_order(), __("Status"));
				}
			}
			if(doc.status != "Closed") {
				if (doc.status != "On Hold") {
					if(flt(doc.per_received) < 100 && allow_receipt) {
						cur_frm.add_custom_button(__('Purchase Receipt'), this.make_purchase_receipt, __('Create'));
						if(doc.is_subcontracted==="Yes" && me.has_unsupplied_items()) {
							cur_frm.add_custom_button(__('Material to Supplier'),
								function() { me.make_stock_entry(); }, __("Transfer"));
						}
					}
					if(flt(doc.per_billed) < 100)
						cur_frm.add_custom_button(__('Purchase Invoice'),
							this.make_purchase_invoice, __('Create'));

					if(flt(doc.per_billed)==0 && doc.status != "Delivered") {
						cur_frm.add_custom_button(__('Payment'), cur_frm.cscript.make_payment_entry, __('Create'));
					}

					if(flt(doc.per_billed)==0) {
						this.frm.add_custom_button(__('Payment Request'),
							function() { me.make_payment_request() }, __('Create'));
					}

					if(!doc.auto_repeat) {
						cur_frm.add_custom_button(__('Subscription'), function() {
							erpnext.utils.make_subscription(doc.doctype, doc.name)
						}, __('Create'))
					}

					if (doc.docstatus === 1 && !doc.inter_company_order_reference) {
						let me = this;
						let internal = me.frm.doc.is_internal_supplier;
						if (internal) {
							let button_label = (me.frm.doc.company === me.frm.doc.represents_company) ? "Internal Sales Order" :
								"Inter Company Sales Order";

							me.frm.add_custom_button(button_label, function() {
								me.make_inter_company_order(me.frm);
							}, __('Create'));
						}

					}
				}

				cur_frm.page.set_inner_btn_group_as_primary(__('Create'));
			}
		} else if(doc.docstatus===0) {
			cur_frm.cscript.add_from_mappers();
		}
	},

	get_items_from_open_material_requests: function() {
		erpnext.utils.map_current_doc({
			method: "erpnext.stock.doctype.material_request.material_request.make_purchase_order_based_on_supplier",
			args: {
				supplier: this.frm.doc.supplier
			},
			source_doctype: "Material Request",
			source_name: this.frm.doc.supplier,
			target: this.frm,
			setters: {
				company: me.frm.doc.company
			},
			get_query_filters: {
				docstatus: ["!=", 2],
				supplier: this.frm.doc.supplier
			},
			get_query_method: "erpnext.stock.doctype.material_request.material_request.get_material_requests_based_on_supplier"
		});
	},

	validate: function() {
		set_schedule_date(this.frm);
	},

	has_unsupplied_items: function() {
		return this.frm.doc['supplied_items'].some(item => item.required_qty > item.supplied_qty)
	},

	make_stock_entry: function() {
		var items = $.map(cur_frm.doc.items, function(d) { return d.bom ? d.item_code : false; });
		var me = this;

		if(items.length >= 1){
			me.raw_material_data = [];
			me.show_dialog = 1;
			let title = __('Transfer Material to Supplier');
			let fields = [
			{fieldtype:'Section Break', label: __('Raw Materials')},
			{fieldname: 'sub_con_rm_items', fieldtype: 'Table', label: __('Items'),
				fields: [
					{
						fieldtype:'Data',
						fieldname:'item_code',
						label: __('Item'),
						read_only:1,
						in_list_view:1
					},
					{
						fieldtype:'Data',
						fieldname:'rm_item_code',
						label: __('Raw Material'),
						read_only:1,
						in_list_view:1
					},
					{
						fieldtype:'Float',
						read_only:1,
						fieldname:'qty',
						label: __('Quantity'),
						read_only:1,
						in_list_view:1
					},
					{
						fieldtype:'Data',
						read_only:1,
						fieldname:'warehouse',
						label: __('Reserve Warehouse'),
						in_list_view:1
					},
					{
						fieldtype:'Float',
						read_only:1,
						fieldname:'rate',
						label: __('Rate'),
						hidden:1
					},
					{
						fieldtype:'Float',
						read_only:1,
						fieldname:'amount',
						label: __('Amount'),
						hidden:1
					},
					{
						fieldtype:'Link',
						read_only:1,
						fieldname:'uom',
						label: __('UOM'),
						hidden:1
					}
				],
				data: me.raw_material_data,
				get_data: function() {
					return me.raw_material_data;
				}
			}
		]

		me.dialog = new frappe.ui.Dialog({
			title: title, fields: fields
		});

		if (me.frm.doc['supplied_items']) {
			me.frm.doc['supplied_items'].forEach((item, index) => {
			if (item.rm_item_code && item.main_item_code && item.required_qty - item.supplied_qty != 0) {
					me.raw_material_data.push ({
						'name':item.name,
						'item_code': item.main_item_code,
						'rm_item_code': item.rm_item_code,
						'item_name': item.rm_item_code,
						'qty': item.required_qty - item.supplied_qty,
						'warehouse':item.reserve_warehouse,
						'rate':item.rate,
						'amount':item.amount,
						'stock_uom':item.stock_uom
					});
					me.dialog.fields_dict.sub_con_rm_items.grid.refresh();
				}
			})
		}

		me.dialog.get_field('sub_con_rm_items').check_all_rows()

		me.dialog.show()
		this.dialog.set_primary_action(__('Transfer'), function() {
			me.values = me.dialog.get_values();
			if(me.values) {
				me.values.sub_con_rm_items.map((row,i) => {
					if (!row.item_code || !row.rm_item_code || !row.warehouse || !row.qty || row.qty === 0) {
						let row_id = i+1;
						frappe.throw(__("Item Code, warehouse and quantity are required on row {0}", [row_id]));
					}
				})
				me._make_rm_stock_entry(me.dialog.fields_dict.sub_con_rm_items.grid.get_selected_children())
				me.dialog.hide()
				}
			});
		}

		me.dialog.get_close_btn().on('click', () => {
			me.dialog.hide();
		});

	},

	_make_rm_stock_entry: function(rm_items) {
		frappe.call({
			method:"erpnext.buying.doctype.purchase_order.purchase_order.make_rm_stock_entry",
			args: {
				purchase_order: cur_frm.doc.name,
				rm_items: rm_items
			}
			,
			callback: function(r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			}
		});
	},

	make_inter_company_order: function(frm) {
		frappe.model.open_mapped_doc({
			method: "erpnext.buying.doctype.purchase_order.purchase_order.make_inter_company_sales_order",
			frm: frm
		});
	},

	make_purchase_receipt: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
			frm: cur_frm,
			freeze_message: __("Creating Purchase Receipt ...")
		})
	},

	make_purchase_invoice: function() {
		frappe.model.open_mapped_doc({
			method: "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_invoice",
			frm: cur_frm
		})
	},

	add_from_mappers: function() {
		/* DH Notes:
			* The code for "Get Items From: Product Bundle" is defined in 'buying.js', not here.
			* This function cannot consolidate multiple Material Request Lines into a Single PO line.
		*/
		var me = this;
		this.frm.add_custom_button(__('Material Request'),
			function() {
				erpnext.utils.map_current_doc({
					method: "erpnext.stock.doctype.material_request.material_request.make_purchase_order",
					source_doctype: "Material Request",
					target: me.frm,
					setters: {
						schedule_date: undefined,
						status: undefined
					},
					get_query_filters: {
						material_request_type: "Purchase",
						docstatus: 1,
						status: ["!=", "Stopped"],
						per_ordered: ["<", 100],
						company: me.frm.doc.company
					}
				})
			}, __("Get Items From"));

		this.frm.add_custom_button(__('Supplier Quotation'),
			/* Datahenge:  This function cannot consolidate multiple Supplier Quotation Lines into a Single PO line. */
			function() {
				erpnext.utils.map_current_doc({
					method: "erpnext.buying.doctype.supplier_quotation.supplier_quotation.make_purchase_order",
					source_doctype: "Supplier Quotation",
					target: me.frm,
					setters: {
						supplier: me.frm.doc.supplier,
						valid_till: undefined
					},
					get_query_filters: {
						docstatus: 1,
						status: ["not in", ["Stopped", "Expired"]],
					}
				})
			}, __("Get Items From"));

		this.frm.add_custom_button(__('Update Rate as per Last Purchase'),
			function() {
				frappe.call({
					"method": "get_last_purchase_rate",
					"doc": me.frm.doc,
					callback: function(r, rt) {
						me.frm.dirty();
						me.frm.cscript.calculate_taxes_and_totals();
					}
				})
			}, __("Tools"));

		this.frm.add_custom_button(__('Link to Material Request'),
		function() {
			var my_items = [];
			for (var i in me.frm.doc.items) {
				if(!me.frm.doc.items[i].material_request){
					my_items.push(me.frm.doc.items[i].item_code);
				}
			}
			frappe.call({
				method: "erpnext.buying.utils.get_linked_material_requests",
				args:{
					items: my_items
				},
				callback: function(r) {
					if(r.exc) return;

					var i = 0;
					var item_length = me.frm.doc.items.length;
					while (i < item_length) {
						var qty = me.frm.doc.items[i].qty;
						(r.message[0] || []).forEach(function(d) {
							if (d.qty > 0 && qty > 0 && me.frm.doc.items[i].item_code == d.item_code && !me.frm.doc.items[i].material_request_item)
							{
								me.frm.doc.items[i].material_request = d.mr_name;
								me.frm.doc.items[i].material_request_item = d.mr_item;
								var my_qty = Math.min(qty, d.qty);
								qty = qty - my_qty;
								d.qty = d.qty  - my_qty;
								me.frm.doc.items[i].stock_qty = my_qty * me.frm.doc.items[i].conversion_factor;
								me.frm.doc.items[i].qty = my_qty;

								frappe.msgprint("Assigning " + d.mr_name + " to " + d.item_code + " (row " + me.frm.doc.items[i].idx + ")");
								if (qty > 0) {
									frappe.msgprint("Splitting " + qty + " units of " + d.item_code);
									var new_row = frappe.model.add_child(me.frm.doc, me.frm.doc.items[i].doctype, "items");
									item_length++;

									for (var key in me.frm.doc.items[i]) {
										new_row[key] = me.frm.doc.items[i][key];
									}

									new_row.idx = item_length;
									new_row["stock_qty"] = new_row.conversion_factor * qty;
									new_row["qty"] = qty;
									new_row["material_request"] = "";
									new_row["material_request_item"] = "";
								}
							}
						});
						i++;
					}
					refresh_field("items");
				}
			});
		}, __("Tools"));
	},

	tc_name: function() {
		this.get_terms();
	},

	items_add: function(doc, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		if(doc.schedule_date) {
			row.schedule_date = doc.schedule_date;
			refresh_field("schedule_date", cdn, "items");
		} else {
			this.frm.script_manager.copy_from_first_row("items", row, ["schedule_date"]);
		}
	},

	unhold_purchase_order: function(){
		cur_frm.cscript.update_status("Resume", "Draft")
	},

	hold_purchase_order: function(){
		var me = this;
		var d = new frappe.ui.Dialog({
			title: __('Reason for Hold'),
			fields: [
				{
					"fieldname": "reason_for_hold",
					"fieldtype": "Text",
					"reqd": 1,
				}
			],
			primary_action: function() {
				var data = d.get_values();
				let reason_for_hold = 'Reason for hold: ' + data.reason_for_hold;

				frappe.call({
					method: "frappe.desk.form.utils.add_comment",
					args: {
						reference_doctype: me.frm.doctype,
						reference_name: me.frm.docname,
						content: __(reason_for_hold),
						comment_email: frappe.session.user,
						comment_by: frappe.session.user_fullname
					},
					callback: function(r) {
						if(!r.exc) {
							me.update_status('Hold', 'On Hold')
							d.hide();
						}
					}
				});
			}
		});
		d.show();
	},

	unclose_purchase_order: function(){
		cur_frm.cscript.update_status('Re-open', 'Submitted')
	},

	close_purchase_order: function(){
		cur_frm.cscript.update_status('Close', 'Closed')
	},

	delivered_by_supplier: function(){
		cur_frm.cscript.update_status('Deliver', 'Delivered')
	},

	items_on_form_rendered: function() {
		set_schedule_date(this.frm);
	},

	schedule_date: function() {
		set_schedule_date(this.frm);
	}
});

// for backward compatibility: combine new and previous states
$.extend(cur_frm.cscript, new erpnext.buying.PurchaseOrderController({frm: cur_frm}));

cur_frm.cscript.update_status= function(label, status){
	frappe.call({
		method: "erpnext.buying.doctype.purchase_order.purchase_order.update_status",
		args: {status: status, name: cur_frm.doc.name},
		callback: function(r) {
			cur_frm.set_value("status", status);
			cur_frm.reload_doc();
		}
	})
}

cur_frm.fields_dict['items'].grid.get_field('project').get_query = function(doc, cdt, cdn) {
	return {
		filters:[
			['Project', 'status', 'not in', 'Completed, Cancelled']
		]
	}
}

cur_frm.fields_dict['items'].grid.get_field('bom').get_query = function(doc, cdt, cdn) {
	var d = locals[cdt][cdn]
	return {
		filters: [
			['BOM', 'item', '=', d.item_code],
			['BOM', 'is_active', '=', '1'],
			['BOM', 'docstatus', '=', '1'],
			['BOM', 'company', '=', doc.company]
		]
	}
}

function set_schedule_date(frm) {
	if(frm.doc.schedule_date){
		erpnext.utils.copy_value_in_all_rows(frm.doc, frm.doc.doctype, frm.doc.name, "items", "schedule_date");
	}
}

function set_target_warehouse(frm) {
	// Farm To People: Set the target Warehouse.
	console.log("set_target_warehouse");
	if(! frm.doc.set_warehouse){
		frappe.db.get_single_value("Buying Settings", "default_target_warehouse").then(val => {
			frm.doc.set_warehouse = val;
		});
	}
}

frappe.provide("erpnext.buying");

frappe.ui.form.on("Purchase Order", "is_subcontracted", function(frm) {
	if (frm.doc.is_subcontracted === "Yes") {
		erpnext.buying.get_default_bom(frm);
	}
});
