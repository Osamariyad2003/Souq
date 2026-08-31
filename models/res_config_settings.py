# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cod_surcharge_product_id = fields.Many2one(
        'product.product', string='COD Surcharge Product',
        config_parameter='souq.cod_surcharge_product_id',
        help='Product used for the auto-added COD surcharge order line. '
             'Leave empty to disable the surcharge (FR-COD-6).')
    cod_surcharge_type = fields.Selection(
        [('fixed', 'Fixed Amount'), ('percent', 'Percentage of Subtotal')],
        string='COD Surcharge Type', default='fixed',
        config_parameter='souq.cod_surcharge_type')
    cod_surcharge_value = fields.Float(
        string='COD Surcharge Value',
        config_parameter='souq.cod_surcharge_value',
        help='Fixed amount, or percentage of the untaxed subtotal, '
             'depending on COD Surcharge Type.')
