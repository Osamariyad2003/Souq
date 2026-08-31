{
    'name': 'Souq Connect',
    'version': '18.0.1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'MENA COD accounting, driver cash settlement, branch stock and ZATCA-style e-invoicing',
    'description': """
Souq Connect
============
A single Odoo 18 module implementing the full order-to-ledger flow for a
MENA retail/distribution business:

* ``souq.branch`` - a branch tied to a warehouse and four accounting
  anchors: cash, driver-clearing, cash-difference, settlement journal.
* COD accounting on ``sale.order`` / ``account.move``: a COD invoice's
  receivable is booked to the branch's driver-clearing account instead
  of the customer's normal receivable account, because in a COD market
  the cash has not arrived yet - a driver is still carrying it.
* ``souq.cod.collection`` / ``souq.driver.settlement`` / ``souq.driver.float``:
  what a driver is expected to bring back, what they actually handed
  in, and the single balanced journal entry that moves the cash and
  clears the driver-clearing account, routing any variance to the
  cash-difference account.
* ``stock.picking`` driver assignment and a "Refuse Delivery / Return on
  Delivery" flow that reverses the stock move and cancels the COD
  invoice with no residual clearing-account balance.
* ZATCA-style QR e-invoicing on ``account.move``: a base64 TLV payload
  (seller name, VAT number, timestamp, total, VAT amount) rendered to a
  QR image on posting, plus a bilingual (AR/EN) RTL-aware invoice report.

See README.md for the full order-to-ledger explanation.
""",
    'author': 'Souq Connect',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'sale', 'stock', 'account', 'sale_stock', 'stock_account'],
    'external_dependencies': {'python': ['qrcode']},
    'data': [
        'security/souq_security.xml',
        'security/ir.model.access.csv',
        'data/souq_cod_sequence.xml',
        'wizard/souq_cod_collect_wizard_views.xml',
        'wizard/souq_delivery_refuse_wizard_views.xml',
        'views/souq_branch_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/souq_cod_collection_views.xml',
        'views/souq_driver_settlement_views.xml',
        'views/souq_driver_float_views.xml',
        'views/souq_branch_transfer_views.xml',
        'views/stock_picking_views.xml',
        'views/account_move_views.xml',
        'report/souq_einvoice_report.xml',
        'views/souq_menu.xml',
    ],
    'installable': True,
    'application': True,
}
