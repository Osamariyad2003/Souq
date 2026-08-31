# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class SouqCodCollectWizard(models.TransientModel):
    """Lets a driver (or cashier on the driver's behalf) declare cash
    collected against one COD collection line, full or partial."""
    _name = 'souq.cod.collect.wizard'
    _description = 'Record COD Cash Collection'

    collection_id = fields.Many2one(
        'souq.cod.collection', string='Collection', required=True,
        ondelete='cascade')
    driver_id = fields.Many2one('res.users', string='Driver', required=True)
    amount_expected = fields.Monetary(related='collection_id.amount_expected',
                                       readonly=True)
    amount_collected = fields.Monetary(string='Amount Collected', required=True)
    currency_id = fields.Many2one(related='collection_id.currency_id')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        collection = self.env['souq.cod.collection'].browse(
            self.env.context.get('active_id'))
        if collection:
            res.update({
                'collection_id': collection.id,
                'driver_id': collection.driver_id.id or self.env.user.id,
                'amount_collected': collection.amount_expected,
            })
        return res

    def action_confirm(self):
        self.ensure_one()
        if self.amount_collected < 0:
            raise UserError(self.env._('Collected amount cannot be negative.'))
        if not self.collection_id.driver_id:
            self.collection_id.driver_id = self.driver_id
        self.collection_id.action_collect(self.amount_collected)
        return {'type': 'ir.actions.act_window_close'}
