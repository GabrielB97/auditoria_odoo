# -*- coding: utf-8 -*-
"""Almacén de eventos de actividad (H1).

Este modelo es la **fuente única de verdad** del producto: acá se guarda, de forma
normalizada, todo lo que ocurre en el ERP (altas, modificaciones, eliminaciones,
accesos y confirmaciones). Lo consumen, a través de la capa de APIs (E1):

  * el asistente conversacional (E2),
  * el motor de auditorías ISO (E3),
  * y los reportes y la analítica (E4).

Característica central: es **append-only** (de solo anexado). Un evento se crea
una vez y ya no puede modificarse ni borrarse — ni siquiera desde la interfaz.
Sin esa garantía, el registro no serviría como evidencia de auditoría.

Decisión de arquitectura: ADR-003 (modelo propio en lugar de OCA `auditlog`).
"""

from odoo import api, fields, models
from odoo.exceptions import UserError


class ActivityEvent(models.Model):
    _name = "activity.event"
    _description = "Evento de actividad normalizado"
    # Los eventos más recientes primero. El `id` desempata los que comparten
    # exactamente la misma marca de tiempo.
    _order = "timestamp desc, id desc"

    # ------------------------------------------------------------------
    # Campos
    # ------------------------------------------------------------------
    # Los cinco primeros campos son los que exige el criterio de aceptación de
    # H1: "cada evento incluye usuario, fecha y hora, modelo, registro afectado
    # y tipo de acción". Van indexados porque son por los que se filtra (H2).

    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Usuario",
        required=True,
        index=True,
        # `restrict` impide borrar un usuario que tenga eventos registrados:
        # si se pudiera, se perdería la trazabilidad de quién hizo qué.
        ondelete="restrict",
    )

    timestamp = fields.Datetime(
        string="Fecha y hora",
        required=True,
        index=True,
        default=fields.Datetime.now,
    )

    model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Modelo",
        required=True,
        index=True,
        ondelete="cascade",
    )

    # Nombre técnico del modelo (p. ej. "res.partner"). Es un campo relacionado
    # pero **almacenado**: así se puede filtrar por texto sin hacer un JOIN
    # contra ir_model en cada consulta.
    model_name = fields.Char(
        string="Nombre técnico",
        related="model_id.model",
        store=True,
        index=True,
    )

    res_id = fields.Integer(
        string="ID del registro",
        index=True,
        help="Identificador del registro sobre el que se produjo el evento.",
    )

    # Se guarda el nombre que tenía el registro **en el momento del evento**.
    # Es intencional: si después se lo renombra o se lo elimina, la evidencia
    # sigue siendo legible ("¿qué borró Juan?" → "Factura F-0001").
    res_name = fields.Char(
        string="Registro",
        help="Nombre del registro al momento del evento (queda congelado).",
    )

    action_type = fields.Selection(
        selection=[
            ("create", "Alta"),
            ("write", "Modificación"),
            ("unlink", "Eliminación"),
            ("read", "Acceso"),
            ("confirm", "Confirmación"),
        ],
        string="Tipo de acción",
        required=True,
        index=True,
    )

    # Detalle de los campos que cambiaron, con su valor anterior y el nuevo:
    #   {"name": {"old": "Juan", "new": "Juan Pérez"}}
    # Se usa un campo Json (no texto) para poder recorrerlo desde el código
    # sin tener que parsearlo. Alimenta a H4 (historial de un registro).
    changes = fields.Json(
        string="Cambios",
        help="Campos modificados: {campo: {old: valor anterior, new: valor nuevo}}.",
    )

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        index=True,
        default=lambda self: self.env.company,
        help="Permite mantener la separación multi-compañía nativa de Odoo.",
    )

    # ------------------------------------------------------------------
    # Inmutabilidad (append-only)
    # ------------------------------------------------------------------
    # Se bloquean `write` y `unlink` a nivel de modelo, no sólo por permisos.
    # De esta forma la restricción vale para cualquier vía de acceso: interfaz,
    # importaciones, XML-RPC o código de otros módulos.
    #
    # Nota: `create` NO se bloquea; anexar eventos es justamente lo que se hace.

    def write(self, vals):
        raise UserError(
            "Los eventos de actividad son inmutables: no pueden modificarse."
        )

    def unlink(self):
        raise UserError(
            "Los eventos de actividad son inmutables: no pueden eliminarse."
        )

    # ------------------------------------------------------------------
    # Presentación
    # ------------------------------------------------------------------
    @api.depends("res_name", "model_name", "action_type")
    def _compute_display_name(self):
        """Texto que se muestra al referenciar un evento.

        Ejemplo: "Prueba 1 — Modificación".
        """
        etiquetas = dict(self._fields["action_type"].selection)
        for evento in self:
            referencia = evento.res_name or evento.model_name or "?"
            evento.display_name = f"{referencia} — {etiquetas.get(evento.action_type, '')}"
