# -*- coding: utf-8 -*-
"""Endpoint REST de consulta de eventos (H2).

Expone `activity.event.search_events()` como una URL HTTP común, para que la
puedan consumir el asistente (E2), la analítica (E4) o cualquier cliente que
hable HTTP, sin tener que conocer el protocolo JSON-RPC de Odoo:

    GET /api/auditoria/eventos?model=res.partner&action=write&page=1

**Este archivo no contiene lógica de negocio, y es a propósito.** Sólo traduce:
lee los parámetros de la URL, convierte tipos, llama al modelo y devuelve JSON.
Toda la lógica —filtros, zonas horarias, paginación, validación— vive en
`activity.event`, donde se puede probar sin levantar un servidor web y donde la
reutilizan por igual las llamadas internas, JSON-RPC y este controlador.

Contrato completo: «Contrato de la API de eventos (H2)» en el vault.
"""

import json

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request

# Parámetros que la URL entrega como texto pero el modelo espera como enteros.
PARAMETROS_ENTEROS = ("user_id", "res_id")

# Parámetros de paginación: no son filtros, van como argumentos aparte.
PARAMETROS_PAGINACION = ("page", "per_page")


class ControladorApiEventos(http.Controller):

    @http.route(
        "/api/auditoria/eventos",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def buscar_eventos(self, **parametros):
        """Consulta de eventos por HTTP.

        `auth="user"` hace que la petición corra **como el usuario autenticado**.
        Es una decisión deliberada por partida doble:

        1. La protección la aplica el framework, no este código. Un descuido al
           comprobar la sesión a mano dejaría el historial de actividad
           accesible sin credenciales — inaceptable en un módulo de auditoría.
        2. Al ejecutarse en el contexto del usuario, los permisos nativos de
           Odoo se aplican solos. Es la base sobre la que se construye H3.

        Efecto secundario: una petición sin sesión no recibe un 401 sino la
        redirección al login que hace Odoo. Los clientes programáticos se
        autentican antes con `/web/session/authenticate`, que es el flujo
        habitual del ERP.
        """
        try:
            filtros, pagina, por_pagina = self._preparar(parametros)
            resultado = request.env["activity.event"].search_events(
                filters=filtros, page=pagina, per_page=por_pagina
            )
        except ValidationError as error:
            # Preguntar mal es un error del cliente, no del servidor.
            return self._responder({"error": str(error)}, 400)
        except AccessError as error:
            return self._responder({"error": str(error)}, 403)

        return self._responder(resultado, 200)

    # ------------------------------------------------------------------
    # Traducción HTTP → Python
    # ------------------------------------------------------------------
    def _preparar(self, parametros):
        """Separa la paginación de los filtros y convierte los tipos.

        Todo lo que viaja en una URL llega como texto: `res_id=42` es la cadena
        `"42"`. Sin esta conversión el dominio compararía un entero contra una
        cadena y la consulta devolvería cero resultados **sin dar error**, que
        es la peor forma posible de fallar en una herramienta de auditoría.
        """
        paginacion = {}
        for nombre in PARAMETROS_PAGINACION:
            if nombre in parametros:
                paginacion[nombre] = self._a_entero(parametros.pop(nombre), nombre)

        filtros = dict(parametros)
        for nombre in PARAMETROS_ENTEROS:
            if nombre in filtros:
                filtros[nombre] = self._a_entero(filtros[nombre], nombre)

        # Las claves desconocidas no se filtran acá: se dejan pasar para que sea
        # el modelo el que las rechace. Así el criterio de qué es un filtro
        # válido vive en un solo lugar.
        return (
            filtros,
            paginacion.get("page", 1),
            paginacion.get("per_page", 50),
        )

    @staticmethod
    def _a_entero(valor, nombre):
        try:
            return int(valor)
        except (TypeError, ValueError):
            raise ValidationError(
                "El parámetro «%s» debe ser un número entero; se recibió «%s»."
                % (nombre, valor)
            )

    @staticmethod
    def _responder(cuerpo, estado):
        """Respuesta JSON con el código de estado que corresponda."""
        return request.make_response(
            json.dumps(cuerpo, ensure_ascii=False, default=str),
            headers=[("Content-Type", "application/json; charset=utf-8")],
            status=estado,
        )
