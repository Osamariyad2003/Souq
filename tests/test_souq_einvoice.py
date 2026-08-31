# -*- coding: utf-8 -*-
from odoo.addons.souq.tests.common import SouqTestCommon
from odoo.addons.souq.models.souq_einvoice import (
    build_zatca_tlv_payload, decode_zatca_tlv_payload)


class TestSouqEinvoiceTlv(SouqTestCommon):

    def test_tlv_round_trip(self):
        payload = build_zatca_tlv_payload(
            seller_name='Souq Test Seller',
            vat_number='300000000000003',
            timestamp_iso='2026-08-28T10:00:00',
            invoice_total=115.0,
            vat_total=15.0,
        )
        import base64
        encoded = base64.b64encode(payload).decode('ascii')
        decoded = decode_zatca_tlv_payload(encoded)
        self.assertEqual(decoded['seller_name'], 'Souq Test Seller')
        self.assertEqual(decoded['vat_number'], '300000000000003')
        self.assertEqual(decoded['timestamp'], '2026-08-28T10:00:00')
        self.assertEqual(decoded['invoice_total'], '115.00')
        self.assertEqual(decoded['vat_total'], '15.00')

    def test_qr_generated_on_post(self):
        self.company.write({'vat': '300000000000003'})
        tax = self.env['account.tax'].create({
            'name': 'Souq Test VAT 15%',
            'amount': 15.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
        })
        self.product.taxes_id = [(6, 0, [tax.id])]

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
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()

        self.assertTrue(invoice.qr_payload)
        decoded = decode_zatca_tlv_payload(invoice.qr_payload)
        self.assertEqual(decoded['vat_number'], '300000000000003')
        self.assertAlmostEqual(float(decoded['invoice_total']), invoice.amount_total, places=2)
        self.assertAlmostEqual(float(decoded['vat_total']), invoice.amount_tax, places=2)
