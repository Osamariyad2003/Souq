# -*- coding: utf-8 -*-
import base64
import io
import json
import logging
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

try:
    import qrcode
except ImportError:  # pragma: no cover - optional dependency
    qrcode = None

# ZATCA (Saudi e-invoicing) simplified-invoice QR tags.
TLV_TAG_SELLER_NAME = 1
TLV_TAG_VAT_NUMBER = 2
TLV_TAG_TIMESTAMP = 3
TLV_TAG_INVOICE_TOTAL = 4
TLV_TAG_VAT_TOTAL = 5


def _tlv_encode(tag, value):
    value_bytes = str(value).encode('utf-8')
    return bytes([tag, len(value_bytes)]) + value_bytes


def build_zatca_tlv_payload(seller_name, vat_number, timestamp_iso,
                             invoice_total, vat_total):
    """Build the raw TLV bytes for a ZATCA-style simplified-invoice QR
    code, from the five mandatory fields."""
    payload = b''.join([
        _tlv_encode(TLV_TAG_SELLER_NAME, seller_name or ''),
        _tlv_encode(TLV_TAG_VAT_NUMBER, vat_number or ''),
        _tlv_encode(TLV_TAG_TIMESTAMP, timestamp_iso or ''),
        _tlv_encode(TLV_TAG_INVOICE_TOTAL, '%.2f' % (invoice_total or 0.0)),
        _tlv_encode(TLV_TAG_VAT_TOTAL, '%.2f' % (vat_total or 0.0)),
    ])
    return payload


def decode_zatca_tlv_payload(base64_payload):
    """Inverse of build_zatca_tlv_payload: given the base64-encoded TLV
    string, return a dict of the five decoded fields. Used by the round-
    trip test and available for support/debugging tooling."""
    raw = base64.b64decode(base64_payload)
    fields_by_tag = {}
    i = 0
    while i < len(raw):
        tag = raw[i]
        length = raw[i + 1]
        value = raw[i + 2:i + 2 + length].decode('utf-8')
        fields_by_tag[tag] = value
        i += 2 + length
    return {
        'seller_name': fields_by_tag.get(TLV_TAG_SELLER_NAME),
        'vat_number': fields_by_tag.get(TLV_TAG_VAT_NUMBER),
        'timestamp': fields_by_tag.get(TLV_TAG_TIMESTAMP),
        'invoice_total': fields_by_tag.get(TLV_TAG_INVOICE_TOTAL),
        'vat_total': fields_by_tag.get(TLV_TAG_VAT_TOTAL),
    }


class AccountMove(models.Model):
    _inherit = 'account.move'

    seller_tax_id = fields.Char(
        string='Seller VAT Number', compute='_compute_seller_tax_id',
        store=True, readonly=False,
        help='Seller VAT/Tax registration number. Defaults from the '
             'invoicing company, editable before posting.')
    buyer_tax_id = fields.Char(
        string='Buyer VAT Number', compute='_compute_buyer_tax_id',
        store=True, readonly=False,
        help='Buyer VAT/Tax registration number, when the customer is '
             'VAT-registered.')
    tax_breakdown = fields.Text(
        string='Tax Breakdown', compute='_compute_tax_breakdown', store=True,
        help='JSON summary of {tax name: base, amount} used to build and '
             'verify the e-invoice QR payload.')
    qr_payload = fields.Text(
        string='QR Payload (base64 TLV)', copy=False, readonly=True)
    qr_image = fields.Binary(string='QR Code', copy=False, readonly=True,
                              attachment=True)
    einvoice_reference = fields.Char(
        string='E-Invoice Reference', copy=False, readonly=True,
        help='Souq Connect e-invoice tracking reference (FR-BASE-4 shared '
             'sequence), independent of the journal invoice number.')

    @api.depends('company_id')
    def _compute_seller_tax_id(self):
        for move in self:
            if not move.seller_tax_id:
                move.seller_tax_id = move.company_id.vat or ''

    @api.depends('partner_id')
    def _compute_buyer_tax_id(self):
        for move in self:
            if not move.buyer_tax_id:
                move.buyer_tax_id = move.partner_id.vat or ''

    @api.depends('line_ids.tax_line_id', 'line_ids.balance', 'amount_tax',
                 'amount_total')
    def _compute_tax_breakdown(self):
        for move in self:
            breakdown = {}
            for line in move.line_ids.filtered('tax_line_id'):
                key = line.tax_line_id.name
                breakdown[key] = breakdown.get(key, 0.0) + abs(line.balance)
            move.tax_breakdown = json.dumps(breakdown)

    def _souq_check_tax_totals_reconcile(self):
        """Guard invoked on post: the sum of the tax lines must match
        amount_tax, within rounding tolerance. Protects the e-invoice QR
        from ever being generated off an inconsistent tax total."""
        precision = self.currency_id.rounding
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue
            tax_line_total = sum(abs(line.balance)
                                  for line in move.line_ids.filtered('tax_line_id'))
            if float_compare(tax_line_total, move.amount_tax, precision_digits=2) != 0:
                raise UserError(self.env._(
                    'Tax totals do not reconcile on invoice %(name)s: tax '
                    'lines sum to %(lines)s but amount_tax is %(total)s.',
                    name=move.name or move.env._('(new)'),
                    lines=tax_line_total, total=move.amount_tax))

    def _souq_build_qr(self):
        self.ensure_one()
        if not self.einvoice_reference:
            self.einvoice_reference = self.env['ir.sequence'].next_by_code(
                'souq.einvoice') or ''
        invoice_date = self.invoice_date or fields.Date.context_today(self)
        timestamp_iso = datetime.combine(invoice_date, datetime.min.time()).isoformat()
        payload = build_zatca_tlv_payload(
            seller_name=self.company_id.name,
            vat_number=self.seller_tax_id,
            timestamp_iso=timestamp_iso,
            invoice_total=self.amount_total,
            vat_total=self.amount_tax,
        )
        self.qr_payload = base64.b64encode(payload).decode('ascii')
        if qrcode is None:
            _logger.warning(
                'python "qrcode" package not installed: QR image not '
                'generated for invoice %s (payload was still computed).',
                self.name)
            return
        img = qrcode.make(self.qr_payload)
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        self.qr_image = base64.b64encode(buffer.getvalue())

    def _post(self, soft=True):
        for move in self.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund')):
            move._souq_check_tax_totals_reconcile()
        posted = super()._post(soft=soft)
        for move in posted.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund')):
            move._souq_build_qr()
        return posted
