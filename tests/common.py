# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class SouqTestCommon(TransactionCase):
    """Shared fixtures for the Souq Connect test suites.

    Builds one branch with four distinct accounts (cash, clearing,
    cash-difference, plus the company's default receivable) and a
    settlement journal, so every module's tests can build on the same
    minimal chart-of-accounts setup instead of repeating boilerplate.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # TransactionCase runs as SUPERUSER_ID (OdooBot), which is not a
        # member of group_souq_manager by default (only base.user_admin
        # is, via security/souq_security.xml). Settlement confirmation
        # is deliberately gated on that group (FR: only Manager/
        # Accountant may confirm settlements), so grant it to whoever is
        # acting as env.user in tests - mirroring a real authorized user
        # rather than weakening the guard itself.
        cls.env.user.write({
            'groups_id': [(4, cls.env.ref('souq.group_souq_manager').id)],
        })

        Account = cls.env['account.account']
        cls.account_cash = Account.create({
            'name': 'Souq Test Branch Cash',
            'code': 'SBC100',
            'account_type': 'asset_cash',
        })
        cls.account_clearing = Account.create({
            'name': 'Souq Test Driver Clearing',
            'code': 'SBC101',
            # Must be a receivable-type account: it holds a real
            # receivable (the invoice line's date_maturity, set from the
            # payment term, is only valid on a receivable/payable
            # account - see account.move.line._check_payable_receivable).
            'account_type': 'asset_receivable',
            'reconcile': True,
        })
        cls.account_cash_diff = Account.create({
            'name': 'Souq Test Cash Difference',
            'code': 'SBC102',
            'account_type': 'expense',
        })

        cls.journal = cls.env['account.journal'].create({
            'name': 'Souq Test Settlement Journal',
            'code': 'SSJ',
            'type': 'cash',
            'company_id': cls.company.id,
        })

        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)

        cls.branch = cls.env['souq.branch'].create({
            'name': 'Test Branch',
            'company_id': cls.company.id,
            'warehouse_id': cls.warehouse.id,
            'cash_account_id': cls.account_cash.id,
            'clearing_account_id': cls.account_clearing.id,
            'cash_diff_account_id': cls.account_cash_diff.id,
            'journal_id': cls.journal.id,
        })

        cls.customer = cls.env['res.partner'].create({'name': 'Souq Test Customer'})
        cls.driver = cls.env['res.users'].create({
            'name': 'Souq Test Driver',
            'login': 'souq_test_driver',
            'email': 'souq_test_driver@example.com',
            'groups_id': [(4, cls.env.ref('souq.group_souq_driver').id)],
        })

        cls.product = cls.env['product.product'].create({
            'name': 'Souq Test Product',
            'type': 'consu',
            'list_price': 100.0,
        })
