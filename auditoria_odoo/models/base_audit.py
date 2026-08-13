# -*- coding: utf-8 -*-
"""Capa de captura: interceptores de las operaciones del ERP (H1).

Acá está el mecanismo que hace que la auditoría sea automática. En lugar de
pedirle a cada módulo que avise lo que hace, se extiende el modelo abstracto
`base` —del que heredan **todos** los modelos de Odoo— y se envuelven sus
operaciones fundamentales:

    create()  → alta
    write()   → modificación (o confirmación, si cambia el estado)
    unlink()  → eliminación
    read()    → acceso

Cada método hace su trabajo normal (llamando a `super()`) y, además, deja
registrado el evento en `activity.event`.

Dos principios que atraviesan todo el archivo:

1. **La auditoría nunca puede romper el ERP.** Si registrar un evento falla,
   se anota el error en el log técnico y la operación del negocio continúa.
   Es preferible perder un evento antes que impedir que alguien facture.

2. **Costo cercano a cero cuando no se audita.** Estos métodos se ejecutan
   miles de veces por minuto en todos los modelos. Por eso la configuración
   se consulta desde una caché en memoria y se descarta lo más pronto posible.
"""

import logging

from odoo import api, fields, models, tools

_logger = logging.getLogger(__name__)


# Modelos que nunca se auditan, por prefijo:
#
#   activity.event  → evitar la recursión infinita (auditar la auditoría).
#   ir. / bus. / base_ → tablas internas de Odoo (vistas, menús, traducciones,
#                        bus de notificaciones); son ruido técnico.
#   mail.tracking   → el tracking nativo, que ya cubre lo suyo.
#   res.users.log   → registro de conexiones interno de Odoo.
PREFIJOS_EXCLUIDOS = (
    "activity.event",
    "ir.",
    "bus.",
    "base_",
    "mail.tracking",
    "res.users.log",
)

# Campos que no se registran: los mantiene Odoo automáticamente y no
# representan una decisión de negocio. Incluirlos ensuciaría la evidencia
# (cada escritura tocaría `write_date` y `write_uid`).
CAMPOS_IGNORADOS = {
    "write_date", "write_uid", "create_date", "create_uid", "__last_update",
}


class Base(models.AbstractModel):
    """Extensión de `base`: todos los modelos de Odoo heredan estos métodos."""

    _inherit = "base"

    # ==================================================================
    # 1. Configuración (con caché)
    # ==================================================================
    @api.model
    @tools.ormcache("model_name")
    def _auditoria_config(self, model_name):
        """Devuelve qué acciones hay que auditar para un modelo dado.

        El decorador `ormcache` guarda el resultado en memoria: la consulta a
        la base de datos se hace **una sola vez por modelo**, no en cada
        operación. Sin esto, cada `create` o `write` del ERP dispararía una
        consulta extra y la degradación sería notable.

        La caché se invalida desde `activity.event.config` cuando la
        configuración cambia.

        :return: dict como {"create": True, "write": True, ...}
                 o {} si el modelo no está configurado (caso más común).
        """
        # Durante la instalación del módulo el modelo de configuración todavía
        # puede no existir en el registro. Se sale sin hacer nada.
        if "activity.event.config" not in self.env:
            return {}

        try:
            configuracion = self.env["activity.event.config"].sudo().search(
                [("model_id.model", "=", model_name)], limit=1
            )
        except Exception:  # p. ej. la tabla aún no fue creada
            return {}

        if not configuracion:
            return {}

        return {
            "create": configuracion.log_create,
            "write": configuracion.log_write,
            "unlink": configuracion.log_unlink,
            "read": configuracion.log_read,
        }

    def _auditoria_activa(self, accion):
        """¿Hay que auditar esta acción sobre este modelo?

        Se ordenan las comprobaciones de la más barata a la más cara, para
        descartar cuanto antes el caso habitual (modelo no auditado).
        """
        # Permite desactivar la auditoría puntualmente. Se usa, por ejemplo, al
        # escribir el propio evento, para no auditar la auditoría.
        if self.env.context.get("auditoria_omitir"):
            return False

        if not self._name or self._name.startswith(PREFIJOS_EXCLUIDOS):
            return False

        # Los modelos transitorios (asistentes/wizards) y los abstractos no
        # persisten datos: auditarlos no aporta evidencia.
        if self._transient or self._abstract:
            return False

        return self._auditoria_config(self._name).get(accion, False)

    # ==================================================================
    # 2. Registro del evento
    # ==================================================================
    def _auditoria_registrar(self, accion, cambios_por_id=None):
        """Crea un evento en `activity.event` por cada registro de `self`.

        :param accion: uno de create / write / unlink / read / confirm.
        :param cambios_por_id: {id_registro: {campo: {"old": ..., "new": ...}}}
        """
        try:
            modelo = self.env["ir.model"].sudo()._get(self._name)
            momento = fields.Datetime.now()
            cambios_por_id = cambios_por_id or {}

            eventos = []
            for registro in self:
                eventos.append({
                    "user_id": self.env.uid,
                    "timestamp": momento,
                    "model_id": modelo.id,
                    "res_id": registro.id,
                    # display_name se lee ANTES de que el registro desaparezca
                    # (importante en las eliminaciones).
                    "res_name": registro.display_name,
                    "action_type": accion,
                    "changes": cambios_por_id.get(registro.id),
                    "company_id": self._auditoria_compania(registro),
                })

            if eventos:
                # `sudo()` porque el usuario común no tiene permiso de escritura
                # sobre activity.event (justamente para que no pueda manipular
                # la evidencia). El autor real queda guardado en `user_id`.
                self.env["activity.event"].sudo().with_context(
                    auditoria_omitir=True
                ).create(eventos)

        except Exception:  # noqa: BLE001 — deliberadamente amplio
            # Principio 1: la auditoría nunca interrumpe la operación del ERP.
            _logger.exception(
                "Auditoría: no se pudo registrar el evento '%s' sobre el modelo '%s'",
                accion, self._name,
            )

    def _auditoria_compania(self, registro):
        """Compañía del registro, si la tiene; si no, la del usuario actual."""
        if "company_id" in registro._fields and registro.company_id:
            return registro.company_id.id
        return self.env.company.id

    def _auditoria_capturar_cambios(self, vals):
        """Arma el detalle "antes y después" de los campos que se van a escribir.

        Debe llamarse **antes** del `super().write()`: después, los valores
        anteriores ya se perdieron.

        Sólo se incluyen los campos que **realmente cambian de valor**. Odoo
        reescribe con frecuencia campos con el valor que ya tenían (al guardar
        un formulario se envía todo, no sólo lo editado); registrar eso
        generaría eventos vacíos que no aportan evidencia.

        :return: {id_registro: {campo: {"old": ..., "new": ...}}}, sin las
                 entradas de los registros que no cambiaron en nada.
        """
        try:
            campos = [
                nombre for nombre in vals
                if nombre in self._fields and nombre not in CAMPOS_IGNORADOS
            ]
            if not campos:
                return {}

            cambios = {}
            for registro in self:
                cambios_registro = {}
                for campo in campos:
                    anterior = self._auditoria_serializar(registro[campo])
                    nuevo = self._auditoria_serializar(vals[campo])
                    if anterior != nuevo:
                        cambios_registro[campo] = {"old": anterior, "new": nuevo}
                if cambios_registro:
                    cambios[registro.id] = cambios_registro
            return cambios
        except Exception:  # noqa: BLE001
            _logger.exception("Auditoría: no se pudieron capturar los cambios")
            return {}

    def auditoria_registrar_confirmacion(self):
        """Registra explícitamente la confirmación de un documento.

        Pensado para llamarse desde el método de confirmación de cada modelo,
        que es la forma **más precisa** de detectar el hecho:

            class SaleOrder(models.Model):
                _inherit = "sale.order"

                def action_confirm(self):
                    resultado = super().action_confirm()
                    self.auditoria_registrar_confirmacion()
                    return resultado

        Se expone como método público porque forma parte de la interfaz del
        módulo: otros módulos (por ejemplo, un puente hacia ventas o compras)
        pueden usarlo sin depender de detalles internos.

        La detección automática por el campo `state` (ver
        `_auditoria_clasificar_escritura`) se mantiene como red de seguridad
        para los modelos que no declaren su confirmación de forma explícita.
        """
        if self._auditoria_activa("write"):
            self._auditoria_registrar("confirm")

    @staticmethod
    def _auditoria_clasificar_escritura(vals):
        """Decide si una escritura es una modificación o una confirmación.

        En Odoo, el avance de un documento por su flujo (borrador → confirmado →
        hecho) se materializa como una escritura sobre el campo `state`. Esa es
        la señal genérica que distingue una "confirmación de documento" de una
        modificación cualquiera, tal como pide el criterio de aceptación de H1.

        Es una heurística: funciona para cualquier modelo sin necesidad de
        conocerlo. Cuando se quiere precisión —saber que se ejecutó
        *exactamente* la acción de confirmar y no cualquier cambio de estado—
        conviene llamar a `auditoria_registrar_confirmacion()` desde el método
        correspondiente del modelo.
        """
        return "confirm" if "state" in vals else "write"

    @staticmethod
    def _auditoria_serializar(valor):
        """Convierte un valor de Odoo en algo que se pueda guardar como JSON."""
        if isinstance(valor, models.BaseModel):
            # Un Many2one se guarda como su id; un One2many/Many2many, como lista.
            return valor.id if len(valor) == 1 else valor.ids
        if hasattr(valor, "isoformat"):  # date / datetime
            return valor.isoformat()
        if isinstance(valor, bytes):  # imágenes, adjuntos: sólo el tamaño
            return f"<{len(valor)} bytes>"
        return valor

    # ==================================================================
    # 3. Interceptores
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        """Alta de registros."""
        registros = super().create(vals_list)
        # Se audita DESPUÉS de crear: recién ahí existen los ids.
        if registros._auditoria_activa("create"):
            registros._auditoria_registrar("create")
        return registros

    def write(self, vals):
        """Modificación de registros.

        Si la escritura toca el campo `state`, se interpreta como una
        **confirmación de documento** (el paso de borrador a confirmado, o
        cualquier otro cambio de estado del flujo). Es lo que pide el criterio
        de aceptación de H1 al hablar de "confirmaciones de documentos".
        """
        accion = self._auditoria_clasificar_escritura(vals)
        auditar = self._auditoria_activa("write")

        # Los valores anteriores hay que leerlos antes de sobrescribirlos.
        cambios = self._auditoria_capturar_cambios(vals) if auditar else {}

        resultado = super().write(vals)

        # Sin cambios reales no hay evento: una escritura que sólo reescribe
        # los mismos valores (o campos técnicos) no es evidencia de nada.
        if auditar and cambios:
            registros_con_cambios = self.filtered(lambda r: r.id in cambios)
            registros_con_cambios._auditoria_registrar(accion, cambios)
        return resultado

    def unlink(self):
        """Eliminación de registros."""
        # Se audita ANTES de borrar: después ya no se podría leer el nombre
        # del registro ni su compañía.
        if self._auditoria_activa("unlink"):
            self._auditoria_registrar("unlink")
        return super().unlink()

    def read(self, fields=None, load="_classic_read"):
        """Lectura de registros (acceso).

        Sólo se registra si el modelo tiene los accesos habilitados de forma
        explícita: ver la advertencia en `activity.event.config`.
        """
        resultado = super().read(fields=fields, load=load)
        if self._auditoria_activa("read"):
            self._auditoria_registrar("read")
        return resultado
