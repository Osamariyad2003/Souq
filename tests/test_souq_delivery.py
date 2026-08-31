# -*- coding: utf-8 -*-
from odoo.addons.souq.tests.common import SouqTestCommon


class TestSouqDelivery(SouqTestCommon):

    def _make_and_deliver_cod_order(self, qty=1, price=100.0):
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
        picking = order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == 'outgoing')
        picking.driver_id = self.driver
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        return order, picking

    def test_driver_propagated_to_collection(self):
        order, picking = self._make_and_deliver_cod_order()
        invoice = order._create_invoices()
        invoice.action_post()
        collection = self.env['souq.cod.collection'].search(
            [('invoice_id', '=', invoice.id)])
        self.assertEqual(collection.driver_id, self.driver)

    def test_return_on_delivery(self):
        order, picking = self._make_and_deliver_cod_order(price=150.0)
        invoice = order._create_invoices()
        invoice.action_post()
        collection = self.env['souq.cod.collection'].search(
            [('invoice_id', '=', invoice.id)])
        self.assertEqual(collection.state, 'pending')

        wizard = self.env['souq.delivery.refuse.wizard'].create({
            'picking_id': picking.id,
            'reason': 'Customer refused at the door',
        })
        wizard.action_confirm()

        self.assertEqual(order.cod_state, 'failed')
        self.assertEqual(collection.state, 'failed')
        self.assertEqual(invoice.state, 'cancel')

        # Stock reversed: a return picking was created and validated.
        returns = self.env['stock.picking'].search([
            ('origin', 'like', picking.name),
            ('id', '!=', picking.id),
        ])
        self.assertTrue(returns)
        self.assertTrue(all(r.state == 'done' for r in returns))

        # No residual clearing-account balance: the only receivable
        # move-lines on the clearing account belong to the cancelled
        # invoice, which is excluded from account balances.
        clearing_lines = self.env['account.move.line'].search([
            ('account_id', '=', self.account_clearing.id),
            ('parent_state', '=', 'posted'),
        ])
        self.assertFalse(clearing_lines)
