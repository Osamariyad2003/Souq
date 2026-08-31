# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class SouqCodCollection(models.Model):
    """One line of 'money a driver is expected to bring back' for one COD
    invoice. Created automatically when a COD invoice is posted.
    """
    _name = 'souq.cod.collection'
    _inherit = ['mail.thread']
    _description = 'Souq COD Cash Collection'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(default='New', copy=False, readonly=True)
    order_id = fields.Many2one('sale.order', string='Order', required=True,
                                readonly=True, ondelete='restrict')
    invoice_id = fields.Many2one('account.move', string='Invoice',
                                  required=True, readonly=True,
                                  ondelete='restrict')
    driver_id = fields.Many2one(
        'res.users', string='Driver',
        domain=lambda self: [('groups_id', 'in',
                               self.env.ref('souq.group_souq_driver').id)])
    driver_partner_id = fields.Many2one(
        related='driver_id.partner_id', store=True,
        string='Driver Partner',
        help='Stored mirror of driver_id.partner_id so res.partner can '
             'expose a proper (dependency-trackable) one2many of its own '
             'collections, e.g. for the custody balance computation.')
    branch_id = fields.Many2one('souq.branch', string='Branch',
                                 required=True, readonly=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)

    amount_expected = fields.Monetary(
        string='Expected Amount', required=True, readonly=True,
        help='The COD invoice total, i.e. what the driver should bring back.')
    amount_collected = fields.Monetary(
        string='Collected Amount', readonly=True,
        help='What the driver actually handed over / declared collected.')
    variance = fields.Monetary(
        string='Variance', compute='_compute_variance', store=True,
        help='amount_collected - amount_expected. Positive: over-collected. '
             'Negative: short.')
    currency_id = fields.Many2one(related='invoice_id.currency_id', store=True)

    state = fields.Selection(
        [('pending', 'Pending'),
         ('collected', 'Collected'),
         ('settled', 'Settled'),
         ('failed', 'Failed')],
        default='pending', required=True, tracking=True, copy=False)
    settlement_id = fields.Many2one(
        'souq.driver.settlement', string='Settlement', readonly=True,
        copy=False)

    _COD_TRANSITIONS = {
        'pending': {'collected', 'failed'},
        'collected': {'settled', 'failed'},
        'settled': set(),
        'failed': set(),
    }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'souq.cod.collection') or 'New'
        return super().create(vals_list)

    @api.depends('amount_collected', 'amount_expected')
    def _compute_variance(self):
        for rec in self:
            rec.variance = rec.amount_collected - rec.amount_expected

    def _set_state(self, target_state):
        for rec in self:
            allowed = self._COD_TRANSITIONS.get(rec.state, set())
            if target_state not in allowed:
                raise UserError(self.env._(
                    'Cannot move collection %(name)s from "%(current)s" '
                    'to "%(target)s".',
                    name=rec.name, current=rec.state, target=target_state))
            rec.state = target_state

    def action_collect(self, amount_collected):
        """Driver declares cash collected against this invoice (full or
        partial). Moves the collection to 'collected' and syncs the
        linked sale order's cod_state."""
        self.ensure_one()
        if not self.driver_id:
            raise UserError(self.env._(
                'A driver must be assigned before recording a collection.'))
        self.write({'amount_collected': amount_collected})
        self._set_state('collected')
        self.order_id.set_cod_state('collected')

    def action_mark_failed(self):
        """Return-on-delivery / collection failure: no cash will ever come
        in for this invoice. The caller is responsible for reversing the
        invoice/stock so no residual clearing balance is left behind."""
        for rec in self:
            rec._set_state('failed')
            rec.order_id.set_cod_state('failed')
