# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.addons.souq.tests.common import SouqTestCommon


class TestSouqCodSurcharge(SouqTestCommon):
    """FR-COD-6: configurable COD surcharge, applied/removed as an order
    line as payment_mode toggles."""

    def _set_surcharge_config(self, product, type_='fixed', value=10.0):
        IrConfig = self.env['ir.config_parameter'].sudo()
        IrConfig.set_param('souq.cod_surcharge_product_id', product.id)
        IrConfig.set_param('souq.cod_surcharge_type', type_)
        IrConfig.set_param('souq.cod_surcharge_value', value)

    def test_fixed_surcharge_added_and_removed(self):
        surcharge_product = self.env['product.product'].create({
            'name': 'COD Fee', 'type': 'service',
        })
        self._set_surcharge_config(surcharge_product, 'fixed', 10.0)

        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 100.0,
            })],
        })
        surcharge_line = order.order_line.filtered('is_souq_cod_surcharge')
        self.assertTrue(surcharge_line)
        self.assertAlmostEqual(surcharge_line.price_unit, 10.0)

        order.payment_mode = 'standard'
        self.assertFalse(order.order_line.filtered('is_souq_cod_surcharge'))

    def test_percent_surcharge_based_on_subtotal(self):
        surcharge_product = self.env['product.product'].create({
            'name': 'COD Fee %', 'type': 'service',
        })
        self._set_surcharge_config(surcharge_product, 'percent', 5.0)

        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 2,
                'price_unit': 100.0,
            })],
        })
        surcharge_line = order.order_line.filtered('is_souq_cod_surcharge')
        self.assertAlmostEqual(surcharge_line.price_unit, 10.0)  # 5% of 200


class TestSouqCodStateGuard(SouqTestCommon):
    """FR-COD-7: an order can only reach 'settled' via a confirmed
    driver settlement, never directly."""

    def test_direct_settle_rejected(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 50.0,
            })],
        })
        order.action_confirm()
        order.set_cod_state('collected')
        with self.assertRaises(UserError):
            order.set_cod_state('settled')

    def test_settle_via_settlement_allowed(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 50.0,
            })],
        })
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
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
        self.assertEqual(order.cod_state, 'settled')


class TestSouqBranchWarehouseSync(SouqTestCommon):
    """FR-STK-1: a COD order's warehouse must match its branch's
    warehouse; it is auto-filled and enforced."""

    def test_warehouse_auto_filled_from_branch(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 50.0,
            })],
        })
        self.assertEqual(order.warehouse_id, self.branch.warehouse_id)

    def test_mismatched_warehouse_rejected(self):
        other_wh = self.env['stock.warehouse'].create({
            'name': 'Other Warehouse', 'code': 'OTH',
            'company_id': self.company.id,
        })
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 50.0,
            })],
        })
        with self.assertRaises(ValidationError):
            order.warehouse_id = other_wh


class TestSouqDriverCustodyBalance(SouqTestCommon):
    """Data requirement: res.partner driver flag + custody balance."""

    def test_custody_balance_tracks_collected_cash(self):
        self.assertTrue(self.driver.partner_id.is_souq_driver)
        self.assertAlmostEqual(self.driver.partner_id.souq_custody_balance, 0.0)

        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'payment_mode': 'cod',
            'branch_id': self.branch.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 80.0,
            })],
        })
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        collection = self.env['souq.cod.collection'].search(
            [('invoice_id', '=', invoice.id)])
        collection.driver_id = self.driver
        collection.action_collect(80.0)

        self.assertAlmostEqual(self.driver.partner_id.souq_custody_balance, 80.0)

        settlement = self.env['souq.driver.settlement'].create({
            'driver_id': self.driver.id,
            'branch_id': self.branch.id,
            'collection_ids': [(4, collection.id)],
            'total_handed_in': 80.0,
        })
        settlement.action_confirm()
        self.assertAlmostEqual(self.driver.partner_id.souq_custody_balance, 0.0)


class TestSouqBranchTransfer(SouqTestCommon):
    """FR-STK-2 / FR-STK-3: inter-branch transfer with a visible
    in-transit state."""

    def test_transfer_in_transit_then_done(self):
        dest_wh = self.env['stock.warehouse'].create({
            'name': 'Dest Warehouse', 'code': 'DWH',
            'company_id': self.company.id,
        })
        dest_branch = self.env['souq.branch'].create({
            'name': 'Dest Branch',
            'company_id': self.company.id,
            'warehouse_id': dest_wh.id,
            'cash_account_id': self.account_cash.id,
            'clearing_account_id': self.account_clearing.id,
            'cash_diff_account_id': self.account_cash_diff.id,
            'journal_id': self.journal.id,
        })
        transfer = self.env['souq.branch.transfer'].create({
            'source_branch_id': self.branch.id,
            'dest_branch_id': dest_branch.id,
            'line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 5,
            })],
        })
        transfer.action_confirm()
        self.assertEqual(transfer.state, 'in_transit')
        self.assertTrue(transfer.outgoing_picking_id)

        transfer.action_receive()
        self.assertEqual(transfer.state, 'done')
        self.assertEqual(transfer.outgoing_picking_id.state, 'done')
        self.assertEqual(transfer.incoming_picking_id.state, 'done')
