# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.addons.souq.tests.common import SouqTestCommon


class TestSouqCod(SouqTestCommon):

    def _make_cod_order(self, qty=1, price=100.0):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'price_unit': price,
            })],
        })
        order.action_confirm()
        return order

    def _invoice_and_post(self, order):
        invoice = order._create_invoices()
        invoice.action_post()
        return invoice

    def test_cod_invoice_posts_to_clearing_account(self):
        order = self._make_cod_order()
        invoice = self._invoice_and_post(order)
        receivable_lines = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable')
        self.assertTrue(receivable_lines)
        self.assertEqual(receivable_lines.account_id, self.account_clearing)

        collection = self.env['souq.cod.collection'].search(
            [('invoice_id', '=', invoice.id)])
        self.assertEqual(len(collection), 1)
        self.assertEqual(collection.state, 'pending')
        self.assertAlmostEqual(collection.amount_expected, invoice.amount_total)

    def test_full_settlement_balances_to_zero(self):
        order = self._make_cod_order()
        invoice = self._invoice_and_post(order)
        collection = self.env['souq.cod.collection'].search(
            [('invoice_id', '=', invoice.id)])
        collection.driver_id = self.driver
        collection.action_collect(invoice.amount_total)
        self.assertEqual(order.cod_state, 'collected')

        settlement = self.env['souq.driver.settlement'].create({
            'driver_id': self.driver.id,
            'branch_id': self.branch.id,
            'collection_ids': [(4, collection.id)],
            'total_handed_in': invoice.amount_total,
        })
        settlement.action_confirm()

        self.assertEqual(settlement.state, 'confirmed')
        self.assertEqual(collection.state, 'settled')
        self.assertEqual(order.cod_state, 'settled')

        move = settlement.move_id
        self.assertEqual(move.state, 'posted')
        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, total_credit)
        self.assertAlmostEqual(total_debit, invoice.amount_total)

        cash_line = move.line_ids.filtered(lambda l: l.account_id == self.account_cash)
        clearing_line = move.line_ids.filtered(lambda l: l.account_id == self.account_clearing)
        self.assertAlmostEqual(cash_line.debit, invoice.amount_total)
        self.assertAlmostEqual(clearing_line.credit, invoice.amount_total)
        diff_lines = move.line_ids.filtered(lambda l: l.account_id == self.account_cash_diff)
        self.assertFalse(diff_lines)

    def test_partial_collection_routes_variance(self):
        order = self._make_cod_order(price=200.0)
        invoice = self._invoice_and_post(order)
        collection = self.env['souq.cod.collection'].search(
            [('invoice_id', '=', invoice.id)])
        collection.driver_id = self.driver
        short_amount = invoice.amount_total - 50.0
        collection.action_collect(short_amount)
        self.assertAlmostEqual(collection.variance, -50.0)

        settlement = self.env['souq.driver.settlement'].create({
            'driver_id': self.driver.id,
            'branch_id': self.branch.id,
            'collection_ids': [(4, collection.id)],
            'total_handed_in': short_amount,
        })
        settlement.action_confirm()

        move = settlement.move_id
        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, total_credit)

        diff_line = move.line_ids.filtered(lambda l: l.account_id == self.account_cash_diff)
        self.assertTrue(diff_line)
        self.assertAlmostEqual(diff_line.debit, 50.0)

    def test_double_settlement_rejected(self):
        order = self._make_cod_order()
        invoice = self._invoice_and_post(order)
        collection = self.env['souq.cod.collection'].search(
            [('invoice_id', '=', invoice.id)])
        collection.driver_id = self.driver
        collection.action_collect(invoice.amount_total)

        settlement = self.env['souq.driver.settlement'].create({
            'driver_id': self.driver.id,
            'branch_id': self.branch.id,
            'collection_ids': [(4, collection.id)],
            'total_handed_in': invoice.amount_total,
        })
        settlement.action_confirm()

        settlement2 = self.env['souq.driver.settlement'].create({
            'driver_id': self.driver.id,
            'branch_id': self.branch.id,
            'total_handed_in': invoice.amount_total,
        })
        with self.assertRaises(UserError):
            settlement2.write({'collection_ids': [(4, collection.id)]})
            settlement2.action_confirm()

    def test_cod_state_illegal_transition_rejected(self):
        order = self._make_cod_order()
        with self.assertRaises(UserError):
            order.set_cod_state('settled')
