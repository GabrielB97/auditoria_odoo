# -*- coding: utf-8 -*-
from odoo import models


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ["sale.order", "audit.trackable.mixin"]

    def action_confirm(self):
        result = super().action_confirm()
        for record in self:
            record._audit_log_event("confirm", res_name=record.display_name)
        return result


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "audit.trackable.mixin"]

    def button_confirm(self):
        result = super().button_confirm()
        for record in self:
            record._audit_log_event("confirm", res_name=record.display_name)
        return result


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "audit.trackable.mixin"]

    def action_post(self):
        result = super().action_post()
        for record in self:
            record._audit_log_event("confirm", res_name=record.display_name)
        return result