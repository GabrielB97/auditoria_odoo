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

from datetime import datetime, time

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# ----------------------------------------------------------------------
# Contrato de la API de consulta (H2)
# ----------------------------------------------------------------------
# Estos valores están fijados en el documento «Contrato de la API de eventos
# (H2)» del vault, porque los consumen E2 (asistente), E3 (motor ISO) y E4
# (analítica). Cambiarlos acá sin actualizar ese documento rompe el acuerdo.

FILTROS_ACEPTADOS = frozenset({
    "user_id", "model", "action", "res_id", "date_from", "date_to", "tz",
})

POR_PAGINA_POR_DEFECTO = 50

# Techo de resultados por página. Sin él, una consulta sin filtros sobre una
# base con millones de eventos intenta materializarlos todos en memoria y
# degrada el ERP para todos los usuarios.
TECHO_POR_PAGINA = 500

FORMATO_FECHA = "%Y-%m-%d"
FORMATO_FECHA_HORA = "%Y-%m-%d %H:%M:%S"


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
    # API de consulta (H2)
    # ------------------------------------------------------------------
    @api.model
    def search_events(self, filters=None, page=1, per_page=POR_PAGINA_POR_DEFECTO):
        """Consulta los eventos de actividad con filtros y paginación.

        Es el punto de entrada que usan el asistente (E2), el motor de
        auditorías (E3) y la analítica (E4). Toda la lógica vive acá y no en el
        controlador HTTP: así se puede probar sin levantar un servidor web, se
        apoya en los permisos nativos de Odoo y sirve igual a una llamada
        interna, a JSON-RPC o a REST.

        :param dict filters: claves aceptadas en `FILTROS_ACEPTADOS`. Se
            combinan con Y lógico. Las claves con valor ``None`` se ignoran,
            para que quien consume pueda armar el diccionario con condiciones
            opcionales sin tener que limpiarlo antes.
        :param int page: número de página, empezando en 1.
        :param int per_page: resultados por página (máximo `TECHO_POR_PAGINA`).

        :return: ``{'results': [...], 'total': int, 'page': int,
                  'pages': int, 'per_page': int}`` con las marcas de tiempo
                  **en UTC**.

        :raise ValidationError: ante cualquier filtro o valor inválido. Es
            deliberado: en una herramienta de auditoría, preguntar mal no puede
            verse igual que "no hay nada". Si alguien filtra por
            ``action='modificacion'`` y recibe cero resultados, concluiría que
            no pasó nada — cuando en realidad se equivocó al preguntar.
        """
        filtros = {c: v for c, v in (filters or {}).items() if v is not None}

        self._search_events_validar_claves(filtros)
        page, per_page = self._search_events_validar_paginacion(page, per_page)
        dominio = self._search_events_construir_dominio(filtros)

        total = self.search_count(dominio)
        # División entera hacia arriba: 5 resultados de a 2 son 3 páginas.
        paginas = -(-total // per_page) if total else 0

        eventos = self.search(
            dominio,
            limit=per_page,
            offset=(page - 1) * per_page,
            # El desempate por `id` es lo que vuelve confiable la paginación:
            # varios eventos pueden compartir el mismo segundo y, sin un orden
            # determinístico, uno podría repetirse entre páginas o saltearse.
            order="timestamp desc, id desc",
        )

        return {
            "results": [self._search_events_serializar(e) for e in eventos],
            "total": total,
            "page": page,
            "pages": paginas,
            "per_page": per_page,
        }

    # -- Validación --------------------------------------------------------

    @api.model
    def _search_events_validar_claves(self, filtros):
        """Rechaza filtros que no existen, en vez de ignorarlos en silencio."""
        desconocidas = set(filtros) - FILTROS_ACEPTADOS
        if desconocidas:
            raise ValidationError(
                "Filtro no reconocido: %s. Los filtros aceptados son: %s."
                % (", ".join(sorted(desconocidas)), ", ".join(sorted(FILTROS_ACEPTADOS)))
            )

    @api.model
    def _search_events_validar_paginacion(self, page, per_page):
        try:
            page, per_page = int(page), int(per_page)
        except (TypeError, ValueError):
            raise ValidationError("«page» y «per_page» deben ser números enteros.")

        if page < 1:
            raise ValidationError("«page» empieza en 1; se recibió %s." % page)
        if not 1 <= per_page <= TECHO_POR_PAGINA:
            raise ValidationError(
                "«per_page» debe estar entre 1 y %s; se recibió %s. El techo "
                "protege al ERP: una consulta sin límite sobre millones de "
                "eventos los materializaría todos en memoria."
                % (TECHO_POR_PAGINA, per_page)
            )
        return page, per_page

    @api.model
    def _search_events_zona_horaria(self, filtros):
        """Zona con la que se interpretan las fechas de los filtros.

        Por defecto, la del usuario que consulta: «el 15 de agosto» significa
        el día 15 *de quien pregunta*, no el día 15 en UTC.
        """
        nombre = filtros.get("tz") or self.env.user.tz or "UTC"
        try:
            return pytz.timezone(nombre)
        except pytz.UnknownTimeZoneError:
            raise ValidationError(
                "Zona horaria desconocida: «%s». Se espera un identificador "
                "IANA, por ejemplo «America/Argentina/Buenos_Aires»." % nombre
            )

    @api.model
    def _search_events_a_utc(self, valor, clave, zona, fin_del_dia=False):
        """Convierte un valor de fecha del filtro a UTC, que es como se guarda.

        Dos formas admitidas, con significados distintos a propósito:

        * ``'2026-08-15'`` (fecha sola) → el **día completo en `zona`**. Es lo
          que alguien quiere decir cuando pide "los eventos del 15".
        * ``'2026-08-15 13:00:00'`` (con hora) → **UTC estricto**, sin
          interpretación: si quien consulta se tomó el trabajo de dar la hora,
          se respeta tal cual.
        """
        if isinstance(valor, datetime):
            return valor

        texto = str(valor).strip()
        try:
            momento = datetime.strptime(texto, FORMATO_FECHA_HORA)
        except ValueError:
            try:
                dia = datetime.strptime(texto, FORMATO_FECHA).date()
            except ValueError:
                raise ValidationError(
                    "Fecha inválida en «%s»: «%s». Se espera «AAAA-MM-DD» "
                    "(día completo en la zona del usuario) o «AAAA-MM-DD "
                    "HH:MM:SS» (UTC)." % (clave, texto)
                )
            # Fecha sola: se estira al día completo en la zona indicada y se
            # traduce a UTC. Con el usuario en UTC-3, el 15 local abarca desde
            # las 03:00 del 15 UTC hasta las 02:59:59 del 16 UTC.
            hora = time(23, 59, 59) if fin_del_dia else time(0, 0, 0)
            local = zona.localize(datetime.combine(dia, hora))
            return local.astimezone(pytz.UTC).replace(tzinfo=None)

        return momento

    # -- Construcción del dominio -----------------------------------------

    @api.model
    def _search_events_construir_dominio(self, filtros):
        """Traduce los filtros del contrato a un dominio de Odoo."""
        dominio = []

        if "user_id" in filtros:
            dominio.append(("user_id", "=", filtros["user_id"]))

        if "res_id" in filtros:
            dominio.append(("res_id", "=", filtros["res_id"]))

        if "model" in filtros:
            modelo = filtros["model"]
            if modelo not in self.env:
                raise ValidationError(
                    "El modelo «%s» no existe en esta instalación de Odoo." % modelo
                )
            # Se filtra por `model_name` (relacionado pero almacenado) para no
            # tener que unir contra ir_model en cada consulta.
            dominio.append(("model_name", "=", modelo))

        if "action" in filtros:
            accion = filtros["action"]
            validas = [v for v, _ in self._fields["action_type"].selection]
            if accion not in validas:
                raise ValidationError(
                    "Tipo de acción inválido: «%s». Los valores aceptados son: "
                    "%s." % (accion, ", ".join(validas))
                )
            dominio.append(("action_type", "=", accion))

        zona = self._search_events_zona_horaria(filtros)
        desde = hasta = None

        if "date_from" in filtros:
            desde = self._search_events_a_utc(filtros["date_from"], "date_from", zona)
            dominio.append(("timestamp", ">=", desde))

        if "date_to" in filtros:
            hasta = self._search_events_a_utc(
                filtros["date_to"], "date_to", zona, fin_del_dia=True
            )
            dominio.append(("timestamp", "<=", hasta))

        if desde and hasta and desde > hasta:
            raise ValidationError(
                "El rango de fechas está invertido: «date_from» (%s) es "
                "posterior a «date_to» (%s)."
                % (filtros["date_from"], filtros["date_to"])
            )

        return dominio

    # -- Serialización -----------------------------------------------------

    @api.model
    def _search_events_serializar(self, evento):
        """Convierte un evento en el diccionario que fija el contrato.

        Las marcas de tiempo salen **en UTC**, siempre. Convertir a la zona de
        quien mira es responsabilidad de quien presenta el dato — la interfaz
        de Odoo ya lo hace sola.
        """
        return {
            "id": evento.id,
            "timestamp": fields.Datetime.to_string(evento.timestamp),
            "user_id": evento.user_id.id,
            "user_name": evento.user_id.display_name,
            "model": evento.model_name,
            "res_id": evento.res_id,
            "res_name": evento.res_name,
            "action": evento.action_type,
            "changes": evento.changes or {},
            "company_id": evento.company_id.id or False,
        }

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
