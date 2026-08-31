# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    payment_mode = fields.Selection(
        [('standard', 'Standard'), ('cod', 'Cash on Delivery')],
        string='Payment Mode', default='standard', required=True,
        tracking=True,
        help='COD orders post their receivable to the branch driver-'
             'clearing account instead of the customer receivable account, '
             'and go through the driver collection/settlement flow.')
    branch_id = fields.Many2one(
        'souq.branch', string='Branch', tracking=True,
        help='Branch fulfilling this order. Required for COD orders: it '
             'determines the clearing account, cash account and driver.')
    cod_state = fields.Selection(
        [('pending', 'Pending'),
         ('collected', 'Collected'),
         ('settled', 'Settled'),
         ('failed', 'Failed')],
        string='COD Status', default='pending', tracking=True, copy=False,
        help='pending -> collected|failed ; collected -> settled|failed. '
             'settled and failed are terminal.')

    _COD_TRANSITIONS = {
        'pending': {'collected', 'failed'},
        'collected': {'settled', 'failed'},
        'settled': set(),
        'failed': set(),
    }

    @api.constrains('payment_mode', 'branch_id')
    def _check_cod_branch_required(self):
        for order in self:
            if order.payment_mode == 'cod' and not order.branch_id:
                raise UserError(self.env._(
                    'A branch is required on COD order %(name)s.',
                    name=order.name))

    @api.constrains('branch_id', 'warehouse_id', 'payment_mode')
    def _check_branch_warehouse_match(self):
        # FR-STK-1: a COD delivery must decrement stock from the selling
        # branch's own warehouse, never a different one.
        for order in self:
            if order.payment_mode == 'cod' and order.branch_id \
                    and order.warehouse_id != order.branch_id.warehouse_id:
                raise ValidationError(self.env._(
                    "COD order %(name)s's warehouse (%(wh)s) does not "
                    "match branch %(branch)s's warehouse (%(branch_wh)s).",
                    name=order.name, wh=order.warehouse_id.name,
                    branch=order.branch_id.name,
                    branch_wh=order.branch_id.warehouse_id.name))

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        for order in self:
            if order.branch_id:
                order.warehouse_id = order.branch_id.warehouse_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._souq_sync_warehouse_vals(vals)
        orders = super().create(vals_list)
        orders._souq_sync_cod_surcharge_line()
        return orders

    def write(self, vals):
        self._souq_sync_warehouse_vals(vals)
        res = super().write(vals)
        if 'payment_mode' in vals or 'branch_id' in vals:
            self._souq_sync_cod_surcharge_line()
        return res

    @api.model
    def _souq_sync_warehouse_vals(self, vals):
        """Auto-fill warehouse_id from branch_id (FR-STK-1) whenever a
        branch is set without an explicit warehouse override."""
        if vals.get('branch_id') and not vals.get('warehouse_id'):
            branch = self.env['souq.branch'].browse(vals['branch_id'])
            vals['warehouse_id'] = branch.warehouse_id.id

    def set_cod_state(self, target_state):
        """Move ``cod_state`` forward, enforcing the legal transition
        graph. Raises a UserError on any illegal jump (e.g. settling a
        pending order, or resurrecting a terminal one).

        FR-COD-7: an order can only reach ``settled`` through a
        confirmed ``souq.driver.settlement`` - never directly - so the
        caller must pass ``souq_from_settlement`` in the context.
        """
        for order in self:
            if target_state == 'settled' \
                    and not self.env.context.get('souq_from_settlement'):
                raise UserError(self.env._(
                    'Order %(name)s can only be marked settled through a '
                    'confirmed driver settlement.', name=order.name))
            allowed = self._COD_TRANSITIONS.get(order.cod_state, set())
            if target_state not in allowed:
                raise UserError(self.env._(
                    'Cannot move order %(name)s COD status from '
                    '"%(current)s" to "%(target)s".',
                    name=order.name, current=order.cod_state,
                    target=target_state))
            order.cod_state = target_state

    def _souq_sync_cod_surcharge_line(self):
        """FR-COD-6: apply the configurable COD surcharge (fixed amount
        or percentage of the untaxed subtotal) as an order line, added
        when payment_mode becomes 'cod' and removed otherwise. No-op if
        no surcharge product is configured (Settings > Souq Connect)."""
        IrConfig = self.env['ir.config_parameter'].sudo()
        product_id = int(IrConfig.get_param('souq.cod_surcharge_product_id', 0) or 0)
        if not product_id:
            return
        product = self.env['product.product'].browse(product_id).exists()
        if not product:
            return
        surcharge_type = IrConfig.get_param('souq.cod_surcharge_type', 'fixed')
        surcharge_value = float(IrConfig.get_param('souq.cod_surcharge_value', 0.0) or 0.0)
        for order in self:
            if order.state not in ('draft', 'sent'):
                continue
            surcharge_line = order.order_line.filtered('is_souq_cod_surcharge')
            if order.payment_mode == 'cod' and surcharge_value:
                base = sum(order.order_line.filtered(
                    lambda l: not l.is_souq_cod_surcharge).mapped('price_subtotal'))
                amount = surcharge_value if surcharge_type == 'fixed' \
                    else base * surcharge_value / 100.0
                if surcharge_line:
                    surcharge_line.price_unit = amount
                else:
                    order.order_line = [(0, 0, {
                        'product_id': product.id,
                        'name': product.name,
                        'product_uom_qty': 1,
                        'price_unit': amount,
                        'is_souq_cod_surcharge': True,
                    })]
            elif surcharge_line:
                surcharge_line.unlink()

    def _create_invoices(self, grouped=False, final=False):
        moves = super()._create_invoices(grouped=grouped, final=final)
        for move in moves:
            orders = move.line_ids.sale_line_ids.order_id
            cod_orders = orders.filtered(
                lambda o: o.payment_mode == 'cod' and o.branch_id)
            if not cod_orders:
                continue
            # A grouped COD invoice must come from a single branch: the
            # clearing account it posts to cannot be split.
            branches = cod_orders.mapped('branch_id')
            if len(branches) > 1:
                raise UserError(self.env._(
                    'Cannot create one invoice for COD orders belonging '
                    'to different branches (%(branches)s).',
                    branches=', '.join(branches.mapped('name'))))
            branch = branches
            move.write({
                'payment_mode': 'cod',
                'branch_id': branch.id,
            })
            receivable_lines = move.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable')
            receivable_lines.write({'account_id': branch.clearing_account_id.id})
        return moves


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_souq_cod_surcharge = fields.Boolean(
        default=False, copy=False,
        help='Set on the line auto-generated for the configurable COD '
             'surcharge (Settings > Souq Connect), so it can be found and '
             'removed/updated as payment_mode changes.')
