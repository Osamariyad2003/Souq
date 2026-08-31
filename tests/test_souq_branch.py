# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from .common import SouqTestCommon


class TestSouqBranch(SouqTestCommon):

    def test_branch_created(self):
        self.assertTrue(self.branch.id)
        self.assertEqual(self.branch.warehouse_id, self.warehouse)

    def test_distinct_accounts_constraint(self):
        with self.assertRaises(ValidationError):
            self.env['souq.branch'].create({
                'name': 'Bad Branch',
                'company_id': self.company.id,
                'warehouse_id': self.warehouse.id,
                'cash_account_id': self.account_cash.id,
                'clearing_account_id': self.account_cash.id,
                'cash_diff_account_id': self.account_cash_diff.id,
                'journal_id': self.journal.id,
            })
