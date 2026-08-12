# -*- coding: utf-8 -*-
import json
from odoo import models

class AuditTrackableMixin(models.AbstractModel):
    """Mixin que registra altas, modificaciones y eliminaciones en
    audit.activity.event. Se aplica explícitamente por modelo con
    _inherit, no a todo Odoo, para no degradar la performance del ERP
    (requisito no funcional del acta de constitución).
    """

    _name = "audit.trackable.mixin"
    _description = "Mixin de auditoría de actividad"

    # Campos técnicos que no aportan valor de auditoría y generan ruido
    # en cada write (se recalculan solos, no son decisiones de negocio).
    # "state" se excluye porque sus transiciones relevantes (confirmar,
    # publicar) ya se registran como evento "confirm" en cada modelo
    # heredado; incluirlo acá duplicaría el evento con menos contexto.
    _audit_ignored_fields = {"write_date", "write_uid", "__last_update", "state"}

    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._audit_log_event("create", res_name=record.display_name)
        return records

    def write(self, vals):
        changes = self._audit_build_field_changes(vals)
        result = super().write(vals)
        if changes:
            for record in self:
                record._audit_log_event(
                    "write",
                    res_name=record.display_name,
                    field_changes=changes.get(record.id),
                )
        return result

    def unlink(self):
        # Se registra antes de borrar: después ya no hay display_name.
        names = {record.id: record.display_name for record in self}
        model_name = self._name
        result = super().unlink()
        event_model = self.env["audit.activity.event"].sudo()
        for res_id, res_name in names.items():
            event_model.create(
                {
                    "res_model": model_name,
                    "res_id": res_id,
                    "res_name": res_name,
                    "action_type": "unlink",
                    "user_id": self.env.uid,
                }
            )
        return result

    def _audit_build_field_changes(self, vals):
        """Arma un diff {id: {campo: {anterior, nuevo}}} antes de aplicar
        el write, comparando solo los campos que realmente cambian de
        valor (evita ruido cuando Odoo reescribe el mismo valor)."""
        tracked_vals = {
            key: value
            for key, value in vals.items()
            if key not in self._audit_ignored_fields
        }
        if not tracked_vals:
            return {}

        changes = {}
        for record in self:
            record_changes = {}
            for field_name, new_value in tracked_vals.items():
                old_value = record[field_name]
                # Comparación simple; para relacionales esto compara ids,
                # que alcanza para saber que "algo cambió" en el evento.
                old_repr = old_value.id if hasattr(old_value, "id") and old_value else old_value
                if old_repr != new_value:
                    record_changes[field_name] = {"anterior": old_repr, "nuevo": new_value}
            if record_changes:
                changes[record.id] = record_changes
        return changes

    def _audit_log_event(self, action_type, res_name=None, field_changes=None):
        self.env["audit.activity.event"].sudo().create(
            {
                "res_model": self._name,
                "res_id": self.id,
                "res_name": res_name or self.display_name,
                "action_type": action_type,
                "user_id": self.env.uid,
                "field_changes": json.dumps(field_changes) if field_changes else False,
            }
        )