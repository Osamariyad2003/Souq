# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class SouqBranchTransfer(models.Model):
    """FR-STK-2 / FR-STK-3: inter-branch stock transfer with a distinct,
    visible in-transit state. Goods leave the source branch's warehouse
    into a shared "Inter-Branch Transit" location (outgoing picking),
    then move from transit into the destination branch's warehouse
    (incoming picking) - two paired stock moves, exactly as specified.
    """
    _name = 'souq.branch.transfer'
    _inherit = ['mail.thread']
    _description = 'Souq Inter-Branch Stock Transfer'
    _order = 'id desc'

    name = fields.Char(default='New', copy=False, readonly=True)
    source_branch_id = fields.Many2one(
        'souq.branch', string='Source Branch', required=True, tracking=True)
    dest_branch_id = fields.Many2one(
        'souq.branch', string='Destination Branch', required=True, tracking=True)
    company_id = fields.Many2one(related='source_branch_id.company_id', store=True)
    line_ids = fields.One2many(
        'souq.branch.transfer.line', 'transfer_id', string='Products')
    state = fields.Selection(
        [('draft', 'Draft'),
         ('in_transit', 'In Transit'),
         ('done', 'Done'),
         ('cancel', 'Cancelled')],
        default='draft', required=True, tracking=True, copy=False)
    outgoing_picking_id = fields.Many2one(
        'stock.picking', string='Outgoing Transfer', readonly=True, copy=False)
    incoming_picking_id = fields.Many2one(
        'stock.picking', string='Incoming Transfer', readonly=True, copy=False)

    @api.constrains('source_branch_id', 'dest_branch_id')
    def _check_different_branches(self):
        for rec in self:
            if rec.source_branch_id and rec.source_branch_id == rec.dest_branch_id:
                raise UserError(self.env._(
                    'Source and destination branches must be different.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'souq.branch.transfer') or 'New'
        return super().create(vals_list)

    def _get_transit_location(self):
        self.ensure_one()
        company = self.company_id
        location = self.env['stock.location'].search([
            ('name', '=', 'Inter-Branch Transit'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not location:
            location = self.env['stock.location'].create({
                'name': 'Inter-Branch Transit',
                'usage': 'transit',
                'company_id': company.id,
                'location_id': self.env.ref('stock.stock_location_locations').id,
            })
        return location

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(self.env._(
                    'Only a draft transfer can be confirmed.'))
            if not rec.line_ids:
                raise UserError(self.env._('Add at least one product line.'))
            transit_location = rec._get_transit_location()
            source_wh = rec.source_branch_id.warehouse_id
            picking_type = source_wh.int_type_id or source_wh.out_type_id
            picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'location_id': source_wh.lot_stock_id.id,
                'location_dest_id': transit_location.id,
                'origin': rec.name,
                'move_ids': [(0, 0, {
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.product_id.uom_id.id,
                    'location_id': source_wh.lot_stock_id.id,
                    'location_dest_id': transit_location.id,
                }) for line in rec.line_ids],
            })
            picking.action_confirm()
            picking.action_assign()
            rec.outgoing_picking_id = picking.id
            rec.state = 'in_transit'

    def action_receive(self):
        """The destination branch confirms receipt: validates the
        outgoing leg (if not already done) and creates+validates the
        incoming leg from transit into the destination warehouse."""
        for rec in self:
            if rec.state != 'in_transit':
                raise UserError(self.env._(
                    'Only an in-transit transfer can be received.'))
            if rec.outgoing_picking_id.state != 'done':
                for move in rec.outgoing_picking_id.move_ids:
                    move.quantity = move.product_uom_qty
                rec.outgoing_picking_id.button_validate()

            transit_location = rec._get_transit_location()
            dest_wh = rec.dest_branch_id.warehouse_id
            picking = self.env['stock.picking'].create({
                'picking_type_id': dest_wh.int_type_id.id,
                'location_id': transit_location.id,
                'location_dest_id': dest_wh.lot_stock_id.id,
                'origin': rec.name,
                'move_ids': [(0, 0, {
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    'product_uom': line.product_id.uom_id.id,
                    'location_id': transit_location.id,
                    'location_dest_id': dest_wh.lot_stock_id.id,
                }) for line in rec.line_ids],
            })
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
            picking.button_validate()
            rec.incoming_picking_id = picking.id
            rec.state = 'done'

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(self.env._('A done transfer cannot be cancelled.'))
            if rec.outgoing_picking_id and rec.outgoing_picking_id.state not in ('done', 'cancel'):
                rec.outgoing_picking_id.action_cancel()
            rec.state = 'cancel'


class SouqBranchTransferLine(models.Model):
    _name = 'souq.branch.transfer.line'
    _description = 'Souq Inter-Branch Stock Transfer Line'

    transfer_id = fields.Many2one('souq.branch.transfer', required=True,
                                   ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity', required=True, default=1.0)
    uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
