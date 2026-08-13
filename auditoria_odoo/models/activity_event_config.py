# -*- coding: utf-8 -*-
"""Configuración de la auditoría, modelo por modelo (H1).

Responde al tercer criterio de aceptación de H1: *"el registro es configurable
por modelo para no degradar la performance del ERP"*.

El enfoque es de **lista blanca**: si un modelo no tiene un registro de
configuración, no se audita. Así, por defecto, el módulo no le agrega trabajo
al ERP; se audita sólo lo que el equipo decide auditar.
"""

from odoo import api, fields, models


class ActivityEventConfig(models.Model):
    _name = "activity.event.config"
    _description = "Configuración de auditoría por modelo"
    _rec_name = "model_id"
    _order = "model_id"

    model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Modelo a auditar",
        required=True,
        ondelete="cascade",
        help="Modelo de Odoo cuyas operaciones se van a registrar.",
    )

    # `active` es un campo especial de Odoo: los registros con active = False
    # quedan archivados y desaparecen de las vistas sin borrarse. Sirve para
    # pausar la auditoría de un modelo sin perder su configuración.
    active = fields.Boolean(string="Activo", default=True)

    # Qué operaciones registrar. Cada una se puede activar por separado.
    log_create = fields.Boolean(string="Registrar altas", default=True)
    log_write = fields.Boolean(string="Registrar modificaciones", default=True)
    log_unlink = fields.Boolean(string="Registrar eliminaciones", default=True)

    # ⚠ Los accesos vienen DESACTIVADOS a propósito.
    #
    # El método read() de Odoo se ejecuta permanentemente: abrir una lista, un
    # formulario o cualquier vista dispara lecturas de todos los registros
    # visibles. Auditarlas siempre generaría un volumen enorme de datos y
    # afectaría la performance.
    #
    # Este fue justamente uno de los problemas detectados al relevar OCA
    # `auditlog` para el ADR-003: abrir una vez la lista de Contactos generó
    # unos ochenta registros de log.
    log_read = fields.Boolean(
        string="Registrar accesos",
        default=False,
        help="Desactivado por defecto: registrar cada lectura genera mucho "
             "volumen y afecta la performance. Activar sólo en modelos "
             "sensibles y por un período acotado.",
    )

    _sql_constraints = [
        (
            "model_uniq",
            "unique(model_id)",
            "Ya existe una configuración de auditoría para ese modelo.",
        ),
    ]

    # ------------------------------------------------------------------
    # Invalidación de la caché
    # ------------------------------------------------------------------
    # La capa de captura (base_audit.py) mantiene esta configuración en caché
    # para no consultar la base de datos en cada operación del ERP. Por eso,
    # cada vez que la configuración cambia hay que invalidar esa caché: si no,
    # los cambios recién se aplicarían al reiniciar Odoo.

    @api.model_create_multi
    def create(self, vals_list):
        registros = super().create(vals_list)
        self.env.registry.clear_cache()
        return registros

    def write(self, vals):
        resultado = super().write(vals)
        self.env.registry.clear_cache()
        return resultado

    def unlink(self):
        resultado = super().unlink()
        self.env.registry.clear_cache()
        return resultado
