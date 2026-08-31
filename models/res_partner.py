# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    """Data requirement: 'res.partner / hr.employee: driver flag and
    custody balance link.' Drivers are modelled as res.users (extending
    the partner already present on every user, per the SRS assumption
    that drivers extend existing employee/partner records) so the flag
    and the money-held-by-this-driver balance are exposed here."""
    _inherit = 'res.partner'

    is_souq_driver = fields.Boolean(
        string='Is Souq Driver', compute='_compute_is_souq_driver', store=True,
        help='True if a user on this partner belongs to the Souq Driver group.')
    souq_collection_ids = fields.One2many(
        'souq.cod.collection', 'driver_partner_id', string='COD Collections',
        help='Every collection ever assigned to a user on this partner, '
             'via souq.cod.collection.driver_partner_id (a stored mirror '
             'of driver_id.partner_id) - kept as a real relation, not a '
             'search(), so souq_custody_balance recomputes correctly.')
    souq_custody_balance = fields.Float(
        string='Cash in Custody', compute='_compute_souq_custody_balance',
        help='Total collected-but-not-yet-settled COD cash currently held '
             'by this driver (sum of amount_collected on their '
             '"collected" state souq.cod.collection records).')

    @api.depends('user_ids.groups_id')
    def _compute_is_souq_driver(self):
        driver_group = self.env.ref('souq.group_souq_driver', raise_if_not_found=False)
        for partner in self:
            partner.is_souq_driver = bool(
                driver_group and (partner.user_ids & driver_group.users))

    @api.depends('souq_collection_ids.state', 'souq_collection_ids.amount_collected')
    def _compute_souq_custody_balance(self):
        for partner in self:
            held = partner.souq_collection_ids.filtered(lambda c: c.state == 'collected')
            partner.souq_custody_balance = sum(held.mapped('amount_collected'))

    def action_view_souq_custody_collections(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Cash in Custody - %s', self.name),
            'res_model': 'souq.cod.collection',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.souq_collection_ids.ids), ('state', '=', 'collected')],
        }
