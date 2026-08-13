# -*- coding: utf-8 -*-
"""Pruebas unitarias de H1 — registro y normalización de eventos.

Cada prueba verifica uno de los criterios de aceptación de la historia:

  * que se registren altas, modificaciones, eliminaciones y confirmaciones;
  * que cada evento tenga usuario, fecha y hora, modelo, registro y acción;
  * que el registro sea configurable por modelo (lista blanca).

Y además la propiedad que sostiene todo el producto: la **inmutabilidad**.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestActivityEvent(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Evento = self.env["activity.event"]
        self.Contacto = self.env["res.partner"]
        self.Config = self.env["activity.event.config"]

        # `res.partner` viene configurado por los datos iniciales del módulo.
        self.config_contacto = self.Config.search(
            [("model_id.model", "=", "res.partner")], limit=1
        )
        self.assertTrue(
            self.config_contacto,
            "res.partner debería estar configurado por los datos iniciales.",
        )

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _eventos_de(self, registro, accion, modelo="res.partner"):
        """Eventos registrados para un registro y una acción concretos."""
        return self.Evento.search([
            ("model_name", "=", modelo),
            ("res_id", "=", registro if isinstance(registro, int) else registro.id),
            ("action_type", "=", accion),
        ])

    # ------------------------------------------------------------------
    # Criterio 1 y 2: se registran las operaciones, con los datos normalizados
    # ------------------------------------------------------------------
    def test_alta_genera_un_evento_completo(self):
        """Crear un registro deja un evento con todos los campos exigidos."""
        contacto = self.Contacto.create({"name": "Contacto de prueba"})

        evento = self._eventos_de(contacto, "create")
        self.assertEqual(len(evento), 1, "El alta debería generar un único evento.")

        # Los cinco datos que pide el criterio de aceptación.
        self.assertEqual(evento.user_id, self.env.user)          # usuario
        self.assertTrue(evento.timestamp)                         # fecha y hora
        self.assertEqual(evento.model_name, "res.partner")        # modelo
        self.assertEqual(evento.res_id, contacto.id)              # registro afectado
        self.assertEqual(evento.res_name, "Contacto de prueba")   # nombre del registro
        self.assertEqual(evento.action_type, "create")            # tipo de acción

    def test_modificacion_guarda_valor_anterior_y_nuevo(self):
        """La modificación registra qué cambió, con su valor previo."""
        contacto = self.Contacto.create({"name": "Nombre original"})
        contacto.write({"name": "Nombre corregido"})

        evento = self._eventos_de(contacto, "write")
        self.assertEqual(len(evento), 1)
        self.assertEqual(evento.changes["name"]["old"], "Nombre original")
        self.assertEqual(evento.changes["name"]["new"], "Nombre corregido")

    def test_eliminacion_conserva_el_nombre_del_registro(self):
        """Al borrar, el evento conserva el nombre: la evidencia sigue siendo legible."""
        contacto = self.Contacto.create({"name": "Contacto a eliminar"})
        id_contacto = contacto.id
        contacto.unlink()

        evento = self._eventos_de(id_contacto, "unlink")
        self.assertEqual(len(evento), 1)
        self.assertEqual(evento.res_name, "Contacto a eliminar")

    def test_un_cambio_de_estado_se_clasifica_como_confirmacion(self):
        """Escribir sobre `state` se interpreta como confirmación de documento."""
        clasificar = self.Contacto._auditoria_clasificar_escritura

        # Avance del documento por su flujo → confirmación.
        self.assertEqual(clasificar({"state": "confirmed"}), "confirm")
        self.assertEqual(clasificar({"state": "done", "name": "X"}), "confirm")

        # Cualquier otra escritura → modificación común.
        self.assertEqual(clasificar({"name": "X"}), "write")
        self.assertEqual(clasificar({}), "write")

    # ------------------------------------------------------------------
    # Señal sobre ruido: sólo se registra lo que cambió de verdad
    # ------------------------------------------------------------------
    def test_reescribir_el_mismo_valor_no_genera_evento(self):
        """Guardar sin cambiar nada no debe dejar evidencia.

        Al guardar un formulario, Odoo reescribe todos los campos, no sólo
        los editados. Registrar eso llenaría la auditoría de eventos vacíos.
        """
        contacto = self.Contacto.create({"name": "Mismo valor"})
        antes = len(self._eventos_de(contacto, "write"))

        contacto.write({"name": "Mismo valor"})          # idéntico al actual

        self.assertEqual(len(self._eventos_de(contacto, "write")), antes,
                         "Reescribir el mismo valor no debería generar un evento.")

    def test_los_campos_tecnicos_no_generan_evento(self):
        """`write_date` y compañía los mantiene Odoo: no son evidencia."""
        contacto = self.Contacto.create({"name": "Campos técnicos"})
        antes = len(self._eventos_de(contacto, "write"))

        contacto.write({"write_date": "2026-01-01 00:00:00"})

        self.assertEqual(len(self._eventos_de(contacto, "write")), antes,
                         "Un cambio de campo técnico no debería generar un evento.")

    def test_solo_se_guardan_los_campos_que_cambiaron(self):
        """Si se escriben dos campos y sólo uno cambia, se registra ese uno."""
        contacto = self.Contacto.create({"name": "Ana", "ref": "REF-1"})
        contacto.write({"name": "Ana", "ref": "REF-2"})   # `name` no cambia

        evento = self._eventos_de(contacto, "write")
        self.assertEqual(len(evento), 1)
        self.assertIn("ref", evento.changes)
        self.assertNotIn("name", evento.changes,
                         "No debería registrarse un campo cuyo valor no cambió.")

    # ------------------------------------------------------------------
    # Confirmación explícita de documentos
    # ------------------------------------------------------------------
    def test_confirmacion_explicita_genera_evento(self):
        """`auditoria_registrar_confirmacion()` deja un evento de confirmación.

        Es el mecanismo preciso, para que cada modelo declare su confirmación
        desde el método que corresponda (`action_confirm`, `action_post`, …).
        """
        contacto = self.Contacto.create({"name": "Documento"})

        contacto.auditoria_registrar_confirmacion()

        evento = self._eventos_de(contacto, "confirm")
        self.assertEqual(len(evento), 1)
        self.assertEqual(evento.res_name, "Documento")

    def test_confirmacion_explicita_respeta_la_configuracion(self):
        """Si el modelo no se audita, la confirmación explícita no registra nada."""
        pais = self.env["res.country.group"].create({"name": "Sin auditar"})

        pais.auditoria_registrar_confirmacion()

        self.assertFalse(self.Evento.search([("model_name", "=", "res.country.group")]))

    # ------------------------------------------------------------------
    # Inmutabilidad (append-only)
    # ------------------------------------------------------------------
    def test_un_evento_no_se_puede_modificar(self):
        contacto = self.Contacto.create({"name": "Inmutable"})
        evento = self._eventos_de(contacto, "create")

        with self.assertRaises(UserError):
            evento.write({"res_name": "valor alterado"})

    def test_un_evento_no_se_puede_eliminar(self):
        contacto = self.Contacto.create({"name": "No borrable"})
        evento = self._eventos_de(contacto, "create")

        with self.assertRaises(UserError):
            evento.unlink()

    # ------------------------------------------------------------------
    # Criterio 3: configurable por modelo (lista blanca)
    # ------------------------------------------------------------------
    def test_un_modelo_no_configurado_no_se_audita(self):
        """Sin configuración no hay auditoría: es lo que protege la performance."""
        antes = self.Evento.search_count([("model_name", "=", "res.country.group")])

        self.env["res.country.group"].create({"name": "Grupo de prueba"})

        despues = self.Evento.search_count([("model_name", "=", "res.country.group")])
        self.assertEqual(antes, despues, "Un modelo sin configurar no debe auditarse.")

    def test_se_puede_desactivar_una_operacion_puntual(self):
        """Desmarcar 'registrar altas' deja de auditar las altas de ese modelo."""
        self.config_contacto.write({"log_create": False})

        contacto = self.Contacto.create({"name": "Sin auditar el alta"})

        self.assertFalse(
            self._eventos_de(contacto, "create"),
            "Con log_create desactivado no debería registrarse el alta.",
        )

    def test_los_accesos_no_se_registran_por_defecto(self):
        """log_read viene desactivado: leer no debe generar eventos."""
        contacto = self.Contacto.create({"name": "Sólo lectura"})
        contacto.read(["name"])

        self.assertFalse(
            self._eventos_de(contacto, "read"),
            "Los accesos no deberían registrarse si log_read está desactivado.",
        )
