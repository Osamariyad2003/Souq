# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class SouqDriverSettlement(models.Model):
    """Batches one driver's collected-but-not-yet-settled COD collections
    for a given day/branch and, on confirmation, posts the single
    balanced journal entry that actually moves cash:

        Dr  Branch Cash          total_handed_in
        Cr  Driver Clearing      total_expected
        Dr/Cr Cash Difference    |variance|   (only if variance != 0)

    where ``variance = total_handed_in - total_expected``. This clears
    exactly the clearing-account balance that was booked at COD invoice
    time and routes any over/short to the cash-difference account, so the
    entry always balances regardless of what the driver actually handed
    in.
    """
    _name = 'souq.driver.settlement'
    _inherit = ['mail.thread']
    _description = 'Souq Driver Cash Settlement'
    _order = 'date desc, id desc'

    name = fields.Char(default='New', copy=False, readonly=True)
    driver_id = fields.Many2one(
        'res.users', string='Driver', required=True, tracking=True,
        domain=lambda self: [('groups_id', 'in',
                               self.env.ref('souq.group_souq_driver').id)])
    date = fields.Date(required=True, default=fields.Date.context_today,
                        tracking=True)
    branch_id = fields.Many2one('souq.branch', string='Branch',
                                 required=True, tracking=True)
    company_id = fields.Many2one(related='branch_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)

    collection_ids = fields.One2many(
        'souq.cod.collection', 'settlement_id', string='Collections')
    total_expected = fields.Monetary(
        string='Total Expected', compute='_compute_totals', store=True)
    total_handed_in = fields.Monetary(
        string='Total Handed In',
        help='Actual cash amount the driver hands in at settlement time.')
    variance = fields.Monetary(
        string='Variance', compute='_compute_totals', store=True,
        help='total_handed_in - total_expected.')

    move_id = fields.Many2one('account.move', string='Journal Entry',
                               readonly=True, copy=False)
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Confirmed')],
        default='draft', required=True, tracking=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'souq.driver.settlement') or 'New'
        return super().create(vals_list)

    @api.depends('collection_ids.amount_expected', 'total_handed_in')
    def _compute_totals(self):
        for rec in self:
            rec.total_expected = sum(rec.collection_ids.mapped('amount_expected'))
            rec.variance = rec.total_handed_in - rec.total_expected

    def action_fetch_collections(self):
        """Link every not-yet-settled 'collected' COD collection for this
        driver/branch onto the settlement. A one2many field has no UI way
        to link pre-existing records (only to create new ones inline), so
        this is the supported way to attach a driver's collections - it
        also matches the SRS wording that a settlement 'aggregates' a
        driver's collections rather than being built one row at a time.
        """
        Collection = self.env['souq.cod.collection']
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._(
                    'Only a draft settlement can fetch new collections.'))
            pending = Collection.search([
                ('driver_id', '=', rec.driver_id.id),
                ('branch_id', '=', rec.branch_id.id),
                ('state', '=', 'collected'),
                ('settlement_id', '=', False),
            ])
            if not pending:
                raise UserError(self.env._(
                    'No collected-but-unsettled collections found for '
                    '%(driver)s at %(branch)s.',
                    driver=rec.driver_id.name, branch=rec.branch_id.name))
            pending.write({'settlement_id': rec.id})

    def action_confirm(self):
        if not (self.env.user.has_group('souq.group_souq_manager')
                or self.env.user.has_group('souq.group_souq_accountant')):
            raise UserError(self.env._(
                'Only a Souq Manager or Souq Accountant can confirm a '
                'driver settlement.'))
        for rec in self:
            if rec.state == 'confirmed':
                raise UserError(self.env._(
                    'Settlement %(name)s is already confirmed.', name=rec.name))
            if not rec.collection_ids:
                raise UserError(self.env._(
                    'Add at least one collection before confirming.'))
            for collection in rec.collection_ids:
                if collection.state == 'settled':
                    raise UserError(self.env._(
                        'Collection %(coll)s was already settled. A '
                        'collection can only be settled once.',
                        coll=collection.name))
                if collection.state != 'collected':
                    raise UserError(self.env._(
                        'Collection %(coll)s is not in "Collected" state '
                        '(currently "%(state)s") and cannot be settled.',
                        coll=collection.name, state=collection.state))
            rec.move_id = rec._create_settlement_move()
            rec.collection_ids._set_state('settled')
            rec.collection_ids.order_id.with_context(
                souq_from_settlement=True).set_cod_state('settled')
            rec.state = 'confirmed'
        return True

    def _create_settlement_move(self):
        self.ensure_one()
        branch = self.branch_id
        currency = self.currency_id
        lines = [(0, 0, {
            'name': self.env._('Driver settlement %s - cash in', self.name),
            'account_id': branch.cash_account_id.id,
            'debit': self.total_handed_in if self.total_handed_in >= 0 else 0.0,
            'credit': -self.total_handed_in if self.total_handed_in < 0 else 0.0,
            'partner_id': self.driver_id.partner_id.id,
        }), (0, 0, {
            'name': self.env._('Driver settlement %s - clear receivable', self.name),
            'account_id': branch.clearing_account_id.id,
            'debit': 0.0,
            'credit': self.total_expected,
            'partner_id': self.driver_id.partner_id.id,
        })]
        if not currency.is_zero(self.variance):
            if self.variance > 0:
                # Handed in more than expected: extra credit to balance.
                lines.append((0, 0, {
                    'name': self.env._('Driver settlement %s - overage', self.name),
                    'account_id': branch.cash_diff_account_id.id,
                    'debit': 0.0,
                    'credit': self.variance,
                }))
            else:
                # Handed in less than expected: extra debit (shortfall/loss).
                lines.append((0, 0, {
                    'name': self.env._('Driver settlement %s - shortfall', self.name),
                    'account_id': branch.cash_diff_account_id.id,
                    'debit': -self.variance,
                    'credit': 0.0,
                }))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': branch.journal_id.id,
            'date': self.date,
            'ref': self.env._('Driver settlement %s', self.name),
            'line_ids': lines,
        })
        move._post()
        return move
