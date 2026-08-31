# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    driver_id = fields.Many2one(
        'res.users', string='Driver', tracking=True,
        domain=lambda self: [('groups_id', 'in',
                               self.env.ref('souq.group_souq_driver').id)],
        help='Driver assigned to carry out this delivery. Propagated to '
             'the matching COD cash collection once it exists.')
    branch_id = fields.Many2one(
        'souq.branch', string='Branch', related='sale_id.branch_id',
        store=True, readonly=True)
    payment_mode = fields.Selection(related='sale_id.payment_mode', store=True,
                                     readonly=True)
    is_returned_on_delivery = fields.Boolean(
        default=False, copy=False,
        help='Set when this delivery was refused by the customer and '
             'reversed through the Refuse Delivery wizard.')

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.driver_id and picking.sale_id \
                    and picking.sale_id.payment_mode == 'cod':
                collections = self.env['souq.cod.collection'].search([
                    ('order_id', '=', picking.sale_id.id),
                    ('driver_id', '=', False),
                ])
                collections.write({'driver_id': picking.driver_id.id})
        return res

    def action_refuse_delivery(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Refuse Delivery / Return on Delivery'),
            'res_model': 'souq.delivery.refuse.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id},
        }
