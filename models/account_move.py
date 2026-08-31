# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    payment_mode = fields.Selection(
        [('standard', 'Standard'), ('cod', 'Cash on Delivery')],
        string='Payment Mode', default='standard', copy=False,
        help='Set automatically when this invoice is created from a COD '
             'sale order. Its receivable line is booked to the branch '
             'driver-clearing account instead of the customer account.')
    branch_id = fields.Many2one(
        'souq.branch', string='Branch', copy=False,
        help='Branch this COD invoice belongs to.')
    souq_collection_ids = fields.One2many(
        'souq.cod.collection', 'invoice_id', string='Cash Collections')

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted:
            if move.payment_mode == 'cod' and move.branch_id \
                    and move.move_type == 'out_invoice' \
                    and not move.souq_collection_ids:
                orders = move.line_ids.sale_line_ids.order_id
                order = orders[:1]
                self.env['souq.cod.collection'].create({
                    'order_id': order.id,
                    'invoice_id': move.id,
                    'branch_id': move.branch_id.id,
                    'amount_expected': move.amount_total,
                })
            # Propagate the delivery driver onto the collection: the
            # picking may already have a driver assigned (delivery
            # happened before invoicing) even though the collection has
            # just been created above with no driver yet.
            for collection in move.souq_collection_ids.filtered(
                    lambda c: not c.driver_id):
                pickings = collection.order_id.picking_ids.filtered(
                    lambda p: p.driver_id and p.state == 'done')
                if pickings:
                    collection.driver_id = pickings[-1].driver_id.id
        return posted
