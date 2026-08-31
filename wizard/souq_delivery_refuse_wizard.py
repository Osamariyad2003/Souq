# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class SouqDeliveryRefuseWizard(models.TransientModel):
    """Return-on-delivery: the customer refuses the parcel at the door.

    Reverses the stock move back into the branch warehouse, cancels the
    COD invoice (so no residual balance is left in the driver-clearing
    account) and moves the order/collection to ``failed``.
    """
    _name = 'souq.delivery.refuse.wizard'
    _description = 'Refuse Delivery / Return on Delivery'

    picking_id = fields.Many2one('stock.picking', required=True, ondelete='cascade')
    reason = fields.Char(string='Reason')

    def action_confirm(self):
        self.ensure_one()
        picking = self.picking_id
        order = picking.sale_id
        if picking.state != 'done':
            raise UserError(self.env._(
                'Only a validated (done) delivery can be refused/returned.'))
        if not order or order.payment_mode != 'cod':
            raise UserError(self.env._(
                'Return on Delivery only applies to COD deliveries.'))

        return_wizard = self.env['stock.return.picking'].with_context(
            active_id=picking.id, active_model='stock.picking').create({})
        # The wizard defaults every return line's quantity to 0 (it
        # expects a human to pick how much to return); a refused
        # delivery always returns everything that was delivered.
        for line in return_wizard.product_return_moves:
            line.quantity = line.move_id.quantity or line.move_id.product_uom_qty
        return_action = return_wizard.action_create_returns()
        return_picking = self.env['stock.picking'].browse(return_action['res_id'])
        for move in return_picking.move_ids:
            move.quantity = move.product_uom_qty
        return_picking.button_validate()
        picking.is_returned_on_delivery = True

        invoices = order.invoice_ids.filtered(lambda m: m.state == 'posted')
        for invoice in invoices:
            if invoice.payment_state not in ('not_paid', False):
                raise UserError(self.env._(
                    'Invoice %(name)s already has payments/reconciliation '
                    'and cannot be auto-cancelled by this wizard.',
                    name=invoice.name))
            invoice.button_cancel()

        collections = self.env['souq.cod.collection'].search(
            [('order_id', '=', order.id), ('state', '!=', 'failed')])
        if collections:
            collections.action_mark_failed()
        else:
            order.set_cod_state('failed')
        return {'type': 'ir.actions.act_window_close'}
