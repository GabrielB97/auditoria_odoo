# -*- coding: utf-8 -*-
"""Pruebas del endpoint REST de consulta de eventos (H2, paso 4).

El controlador **no tiene lógica**: traduce HTTP a una llamada a
``search_events()`` y de vuelta. Por eso estas pruebas no repiten lo que ya
cubren las 29 del modelo — verifican sólo lo que es propio de la capa HTTP:

  * que exija autenticación;
  * que convierta los parámetros de la URL, que siempre llegan como texto;
  * que traduzca los errores del modelo al código de estado correcto;
  * que el JSON tenga la forma que fija el contrato.

Usan ``HttpCase`` porque necesitan un servidor HTTP de verdad; por eso hay que
correrlas **sin** ``--no-http``.
"""

import json

from odoo.tests import HttpCase, tagged

RUTA = "/api/auditoria/eventos"


@tagged("post_install", "-at_install")
class TestApiEventos(HttpCase):

    def setUp(self):
        super().setUp()
        self.Evento = self.env["activity.event"]
        self.modelo = self.env["ir.model"]._get("res.country.group")

        # Usuario propio con credenciales conocidas: no se depende de cuál sea
        # la contraseña del administrador en cada base.
        self.clave = "clave_api_h2"
        self.usuario = self.env["res.users"].create({
            "name": "Consumidor de la API",
            "login": "consumidor_api_h2",
            "password": self.clave,
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })

        self.evento = self.Evento.create({
            "timestamp": "2026-08-15 12:00:00",
            "model_id": self.modelo.id,
            "user_id": self.usuario.id,
            "action_type": "write",
            "res_id": 42,
            "res_name": "Registro de prueba API",
            "changes": {"phone": {"old": "111", "new": "222"}},
        })

    def _consultar(self, consulta=""):
        return self.url_open(RUTA + consulta)

    # ------------------------------------------------------------------
    # Autenticación
    # ------------------------------------------------------------------
    def test_sin_autenticar_no_devuelve_eventos(self):
        """El historial de actividad no puede consultarse sin credenciales.

        Odoo, con `auth='user'`, redirige al login antes de ejecutar el
        controlador. Lo que se verifica acá es la propiedad que importa: que la
        respuesta **no traiga eventos**, sea cual sea la forma del rechazo.
        """
        respuesta = self._consultar("?model=res.country.group")

        self.assertNotIn(
            "Registro de prueba API", respuesta.text,
            "Una petición sin autenticar no debería devolver ningún evento.",
        )

    # ------------------------------------------------------------------
    # Consulta correcta
    # ------------------------------------------------------------------
    def test_devuelve_los_eventos_en_json(self):
        self.authenticate(self.usuario.login, self.clave)

        respuesta = self._consultar("?model=res.country.group&res_id=42")

        self.assertEqual(respuesta.status_code, 200)
        cuerpo = json.loads(respuesta.text)
        self.assertEqual(cuerpo["total"], 1)
        self.assertEqual(cuerpo["results"][0]["res_name"], "Registro de prueba API")

    def test_el_json_trae_los_metadatos_de_paginacion(self):
        self.authenticate(self.usuario.login, self.clave)

        respuesta = self._consultar("?model=res.country.group&page=1&per_page=10")

        cuerpo = json.loads(respuesta.text)
        for clave in ("results", "total", "page", "pages", "per_page"):
            self.assertIn(clave, cuerpo, f"Falta «{clave}» en la respuesta JSON.")
        self.assertEqual(cuerpo["per_page"], 10)

    def test_convierte_los_parametros_numericos(self):
        """Todo lo que viaja en una URL es texto: `res_id=42` llega como "42".

        Si el controlador no convirtiera los tipos, el dominio compararía un
        entero contra una cadena y la consulta no devolvería nada — sin error,
        que es la peor forma de fallar en una herramienta de auditoría.
        """
        self.authenticate(self.usuario.login, self.clave)

        respuesta = self._consultar("?model=res.country.group&res_id=42")

        self.assertEqual(json.loads(respuesta.text)["total"], 1)

    def test_el_detalle_de_cambios_viaja_completo(self):
        self.authenticate(self.usuario.login, self.clave)

        respuesta = self._consultar("?model=res.country.group&res_id=42")

        evento = json.loads(respuesta.text)["results"][0]
        self.assertEqual(evento["changes"]["phone"]["new"], "222")

    # ------------------------------------------------------------------
    # Errores
    # ------------------------------------------------------------------
    def test_un_filtro_invalido_devuelve_400_con_el_motivo(self):
        """Preguntar mal se responde con un error, no con una lista vacía."""
        self.authenticate(self.usuario.login, self.clave)

        respuesta = self._consultar("?action=modificacion")

        self.assertEqual(respuesta.status_code, 400)
        cuerpo = json.loads(respuesta.text)
        self.assertIn("error", cuerpo)
        self.assertIn("modificacion", cuerpo["error"])

    def test_un_filtro_desconocido_devuelve_400(self):
        self.authenticate(self.usuario.login, self.clave)

        respuesta = self._consultar("?usuario=1")

        self.assertEqual(respuesta.status_code, 400)

    def test_un_parametro_numerico_no_numerico_devuelve_400(self):
        self.authenticate(self.usuario.login, self.clave)

        respuesta = self._consultar("?res_id=abc")

        self.assertEqual(respuesta.status_code, 400)
