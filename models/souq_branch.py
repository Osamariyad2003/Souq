# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SouqBranch(models.Model):
    """A physical retail/distribution branch.

    Every branch is tied to a warehouse (for stock) and to four accounting
    anchors that make the COD (cash-on-delivery) flow work as real
    double-entry bookkeeping instead of a cosmetic status field:

    * ``cash_account_id``      - the branch's physical cash-in-hand account.
    * ``clearing_account_id``  - an intermediate asset account. COD
      receivables are booked here at invoice time (money is legally owed
      by the customer but has not reached any cash account yet).
    * ``cash_diff_account_id`` - absorbs over/short variances discovered
      when a driver settles (hands in more/less cash than expected).
    * ``journal_id``           - the journal used for settlement entries.
    """

    _name = 'souq.branch'
    _description = 'Souq Connect Branch'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True,
        domain="[('company_id', '=', company_id)]")
    cash_account_id = fields.Many2one(
        'account.account', string='Cash Account', required=True,
        help='Physical cash-in-hand account for this branch.')
    clearing_account_id = fields.Many2one(
        'account.account', string='Driver Clearing Account', required=True,
        domain=[('account_type', '=', 'asset_receivable')],
        help='Intermediate asset/receivable account used as the '
             'receivable target for COD invoices until the driver settles '
             'collected cash. Must be a receivable-type account: Odoo '
             "requires a due date on receivable lines (and vice versa), "
             'so this account has to belong to that type for the '
             "invoice's own payment-term due date to remain valid after "
             'the line is redirected here.')
    cash_diff_account_id = fields.Many2one(
        'account.account', string='Cash Difference Account', required=True,
        help='Account that absorbs over/short variances at driver '
             'settlement time.')
    journal_id = fields.Many2one(
        'account.journal', string='Settlement Journal', required=True,
        help='Journal used to post driver settlement entries.')

    quant_count = fields.Integer(
        string='Stock Lines', compute='_compute_quant_count')

    @api.depends('warehouse_id')
    def _compute_quant_count(self):
        Quant = self.env['stock.quant']
        for branch in self:
            branch.quant_count = Quant.search_count([
                ('location_id', 'child_of', branch.warehouse_id.view_location_id.id),
                ('quantity', '!=', 0),
            ]) if branch.warehouse_id else 0

    def action_view_branch_stock(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Stock on Hand - %s', self.name),
            'res_model': 'stock.quant',
            'view_mode': 'list,form',
            'domain': [('location_id', 'child_of', self.warehouse_id.view_location_id.id)],
            'context': {'search_default_internal_loc': 1},
        }

    _sql_constraints = [
        ('name_company_uniq', 'unique(name, company_id)',
         'A branch with this name already exists for this company.'),
    ]

    @api.constrains('cash_account_id', 'clearing_account_id',
                     'cash_diff_account_id')
    def _check_distinct_accounts(self):
        for branch in self:
            accounts = branch.cash_account_id + branch.clearing_account_id \
                + branch.cash_diff_account_id
            if len(accounts) != len(set(accounts.ids)):
                raise ValidationError(
                    self.env._(
                        'Cash, clearing and cash-difference accounts must '
                        'be three distinct accounts on branch %(name)s.',
                        name=branch.name))

    @api.constrains('clearing_account_id')
    def _check_clearing_account_type(self):
        # Odoo requires a due date on receivable/payable lines, and only
        # on those (account.move.line._check_payable_receivable). The
        # invoice line's date_maturity (from the payment term) survives
        # being redirected to this account only if it stays a receivable
        # account.
        for branch in self:
            if branch.clearing_account_id.account_type != 'asset_receivable':
                raise ValidationError(self.env._(
                    'Driver Clearing Account on branch %(name)s must be a '
                    'receivable-type account.', name=branch.name))
