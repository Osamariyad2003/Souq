# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SouqDriverFloat(models.Model):
    """Tracks a driver's cash float (petty cash carried for change-giving)
    for a given day, independent of COD collections."""
    _name = 'souq.driver.float'
    _description = 'Souq Driver Cash Float'
    _order = 'date desc'

    driver_id = fields.Many2one(
        'res.users', string='Driver', required=True,
        domain=lambda self: [('groups_id', 'in',
                               self.env.ref('souq.group_souq_driver').id)])
    date = fields.Date(required=True, default=fields.Date.context_today)
    opening_balance = fields.Monetary(string='Opening Balance')
    closing_balance = fields.Monetary(string='Closing Balance')
    difference = fields.Monetary(
        string='Difference', compute='_compute_difference', store=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)

    @api.depends('opening_balance', 'closing_balance')
    def _compute_difference(self):
        for rec in self:
            rec.difference = rec.closing_balance - rec.opening_balance
