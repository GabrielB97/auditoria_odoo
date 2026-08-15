# -*- coding: utf-8 -*-
"""Pruebas de la API de consulta de eventos (H2).

Estas pruebas se escribieron **antes** que la implementación, a partir del
contrato acordado en «Contrato de la API de eventos (H2)» del vault. Cada una
verifica una cláusula concreta de ese contrato, así que si alguna falla lo que
hay que revisar es si el código se apartó del acuerdo — no al revés.

Están agrupadas siguiendo las secciones del contrato:

  1. Filtros (uno por uno y combinados)
  2. Zonas horarias — la parte más delicada
  3. Paginación
  4. Orden
  5. Errores: preguntar mal nunca puede parecerse a "no hay nada"
  6. Forma de la respuesta

Las pruebas trabajan sobre modelos que **no están auditados** (`res.country`,
`res.country.group`), de modo que los eventos que crean sean exactamente los
que declaran y no aparezcan eventos colaterales generados por el propio ERP.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

# Zona horaria de prueba: UTC-3. Es la del equipo, y hace visible el desfase
# entre lo que guarda la base (UTC) y lo que significa "el día 15" para quien
# consulta desde Argentina.
TZ_LOCAL = "America/Argentina/Buenos_Aires"


@tagged("post_install", "-at_install")
class TestSearchEvents(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Evento = self.env["activity.event"]

        # Modelos de referencia. No están en la lista blanca de auditoría, así
        # que ningún registro de estas tablas genera eventos por su cuenta.
        self.modelo_a = self.env["ir.model"]._get("res.country.group")
        self.modelo_b = self.env["ir.model"]._get("res.country")

        self.usuario_1 = self.env.ref("base.user_admin")
        self.usuario_2 = self.env["res.users"].create({
            "name": "Auditor de prueba",
            "login": "auditor_prueba_h2",
        })

        # El usuario que consulta trabaja en UTC-3: es lo que da sentido a las
        # pruebas de zona horaria.
        self.env.user.tz = TZ_LOCAL

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _crear_evento(self, timestamp, modelo=None, usuario=None,
                      accion="write", res_id=1, res_name="Registro", cambios=None):
        """Crea un evento con valores explícitos.

        Se escribe todo en el `create` porque el modelo es append-only: una vez
        creado el evento ya no se puede modificar.
        """
        return self.Evento.create({
            "timestamp": timestamp,
            "model_id": (modelo or self.modelo_a).id,
            "user_id": (usuario or self.usuario_1).id,
            "action_type": accion,
            "res_id": res_id,
            "res_name": res_name,
            "changes": cambios,
        })

    def _buscar(self, **kwargs):
        """Atajo: consulta acotada al modelo de prueba salvo que se indique otro."""
        filtros = kwargs.pop("filters", {})
        filtros.setdefault("model", "res.country.group")
        return self.Evento.search_events(filters=filtros, **kwargs)

    def _ids(self, respuesta):
        return [r["id"] for r in respuesta["results"]]

    # ==================================================================
    # 1. Filtros
    # ==================================================================
    def test_sin_filtros_devuelve_eventos(self):
        """Sin filtros la API responde igual: no es un error, es "todo"."""
        self._crear_evento("2026-08-10 12:00:00")

        respuesta = self.Evento.search_events()

        self.assertGreaterEqual(respuesta["total"], 1)
        self.assertIn("results", respuesta)

    def test_filtra_por_usuario(self):
        """El criterio de aceptación pide poder filtrar por usuario."""
        mio = self._crear_evento("2026-08-10 12:00:00", usuario=self.usuario_1)
        self._crear_evento("2026-08-10 12:00:00", usuario=self.usuario_2)

        respuesta = self._buscar(filters={"user_id": self.usuario_1.id})

        self.assertEqual(self._ids(respuesta), [mio.id])

    def test_filtra_por_modelo(self):
        """Filtrar por modelo no debe traer eventos de otros modelos."""
        del_a = self._crear_evento("2026-08-10 12:00:00", modelo=self.modelo_a)
        self._crear_evento("2026-08-10 12:00:00", modelo=self.modelo_b)

        respuesta = self.Evento.search_events(filters={"model": "res.country.group"})

        self.assertIn(del_a.id, self._ids(respuesta))
        self.assertTrue(
            all(r["model"] == "res.country.group" for r in respuesta["results"]),
            "El filtro por modelo no debería devolver eventos de otros modelos.",
        )

    def test_filtra_por_tipo_de_accion(self):
        """Altas, modificaciones, bajas, accesos y confirmaciones se distinguen."""
        alta = self._crear_evento("2026-08-10 12:00:00", accion="create")
        self._crear_evento("2026-08-10 12:00:00", accion="write")
        self._crear_evento("2026-08-10 12:00:00", accion="unlink")

        respuesta = self._buscar(filters={"action": "create"})

        self.assertEqual(self._ids(respuesta), [alta.id])

    def test_filtra_por_registro_puntual(self):
        """`res_id` acota a un registro concreto: es la base de H4."""
        buscado = self._crear_evento("2026-08-10 12:00:00", res_id=42)
        self._crear_evento("2026-08-10 12:00:00", res_id=99)

        respuesta = self._buscar(filters={"res_id": 42})

        self.assertEqual(self._ids(respuesta), [buscado.id])

    def test_los_filtros_se_combinan_con_y_logico(self):
        """Varios filtros a la vez acotan; no se suman resultados."""
        esperado = self._crear_evento(
            "2026-08-10 12:00:00", usuario=self.usuario_1, accion="create", res_id=7)
        # Cada uno falla en exactamente una condición.
        self._crear_evento("2026-08-10 12:00:00", usuario=self.usuario_2,
                           accion="create", res_id=7)
        self._crear_evento("2026-08-10 12:00:00", usuario=self.usuario_1,
                           accion="write", res_id=7)
        self._crear_evento("2026-08-10 12:00:00", usuario=self.usuario_1,
                           accion="create", res_id=8)

        respuesta = self._buscar(filters={
            "user_id": self.usuario_1.id, "action": "create", "res_id": 7,
        })

        self.assertEqual(self._ids(respuesta), [esperado.id])

    # ==================================================================
    # 2. Zonas horarias
    # ==================================================================
    def test_la_respuesta_devuelve_utc(self):
        """El contrato fija UTC en la salida: sin ambigüedad para quien consume."""
        evento = self._crear_evento("2026-08-15 13:37:39")

        respuesta = self._buscar(filters={"res_id": evento.res_id})

        self.assertEqual(respuesta["results"][0]["timestamp"], "2026-08-15 13:37:39")

    def test_una_fecha_sola_abarca_el_dia_completo_del_usuario(self):
        """«El 15 de agosto» significa el 15 **del usuario**, no el 15 UTC.

        Es la prueba central del contrato. Con el usuario en UTC-3:

          * 2026-08-16 01:00 UTC  =  15/08 22:00 local  → SÍ es del día 15
          * 2026-08-15 02:00 UTC  =  14/08 23:00 local  → NO es del día 15

        Si se interpretaran los filtros como UTC estricto, el primero quedaría
        afuera y el segundo adentro: la consulta respondería sobre una ventana
        distinta de la que se preguntó, sin avisar.
        """
        de_noche = self._crear_evento("2026-08-16 01:00:00", res_name="22h del 15")
        vispera = self._crear_evento("2026-08-15 02:00:00", res_name="23h del 14")

        respuesta = self._buscar(filters={
            "date_from": "2026-08-15", "date_to": "2026-08-15",
        })

        ids = self._ids(respuesta)
        self.assertIn(de_noche.id, ids,
                      "Un evento de las 22:00 hora local es del día 15.")
        self.assertNotIn(vispera.id, ids,
                         "Un evento de las 23:00 del día 14 no es del día 15.")

    def test_una_fecha_con_hora_se_interpreta_como_utc_estricto(self):
        """Si quien consulta da la hora, se respeta tal cual: sin conversión."""
        dentro = self._crear_evento("2026-08-15 14:00:00")
        fuera = self._crear_evento("2026-08-15 12:00:00")

        respuesta = self._buscar(filters={"date_from": "2026-08-15 13:00:00"})

        ids = self._ids(respuesta)
        self.assertIn(dentro.id, ids)
        self.assertNotIn(fuera.id, ids)

    def test_se_puede_indicar_una_zona_horaria_explicita(self):
        """`tz` permite consultar el día de otra zona, no la del que consulta."""
        evento = self._crear_evento("2026-08-15 23:30:00")  # 20:30 en UTC-3

        # En UTC el evento es del 15; en Tokio (UTC+9) ya es el 16.
        en_argentina = self._buscar(filters={
            "date_from": "2026-08-15", "date_to": "2026-08-15", "tz": TZ_LOCAL})
        en_tokio = self._buscar(filters={
            "date_from": "2026-08-15", "date_to": "2026-08-15", "tz": "Asia/Tokyo"})

        self.assertIn(evento.id, self._ids(en_argentina))
        self.assertNotIn(evento.id, self._ids(en_tokio))

    def test_el_rango_de_fechas_incluye_los_extremos(self):
        """`date_from` y `date_to` son inclusivos, como dice el contrato."""
        primero = self._crear_evento("2026-08-10 00:00:00", res_name="borde inicial")
        ultimo = self._crear_evento("2026-08-12 23:59:59", res_name="borde final")

        respuesta = self._buscar(filters={
            "date_from": "2026-08-10", "date_to": "2026-08-12", "tz": "UTC",
        })

        ids = self._ids(respuesta)
        self.assertIn(primero.id, ids)
        self.assertIn(ultimo.id, ids)

    # ==================================================================
    # 3. Paginación
    # ==================================================================
    def test_por_pagina_limita_la_cantidad_de_resultados(self):
        for i in range(5):
            self._crear_evento(f"2026-08-10 12:00:0{i}")

        respuesta = self._buscar(per_page=2)

        self.assertEqual(len(respuesta["results"]), 2)

    def test_el_total_cuenta_todos_los_que_cumplen_el_filtro(self):
        """`total` no es el tamaño de la página: es cuántos hay en total.

        Sin este dato, quien consume no sabe si hay más páginas ni puede decir
        "1240 eventos encontrados".
        """
        for i in range(5):
            self._crear_evento(f"2026-08-10 12:00:0{i}")

        respuesta = self._buscar(per_page=2)

        self.assertEqual(respuesta["total"], 5)
        self.assertEqual(respuesta["pages"], 3)

    def test_las_paginas_no_se_superponen_ni_saltean(self):
        """Recorrer todas las páginas devuelve cada evento exactamente una vez.

        Todos los eventos comparten la misma marca de tiempo a propósito: es el
        caso que rompe la paginación si el orden no tiene un desempate estable.
        """
        creados = {self._crear_evento("2026-08-10 12:00:00").id for _ in range(5)}

        recorridos = []
        for pagina in (1, 2, 3):
            recorridos += self._ids(self._buscar(page=pagina, per_page=2))

        self.assertEqual(len(recorridos), len(set(recorridos)),
                         "Un mismo evento apareció en más de una página.")
        self.assertEqual(set(recorridos), creados,
                         "Recorrer las páginas no devolvió todos los eventos.")

    def test_una_pagina_mas_alla_del_total_no_es_un_error(self):
        """Llegar al final no es preguntar mal: devuelve vacío, con metadatos."""
        self._crear_evento("2026-08-10 12:00:00")

        respuesta = self._buscar(page=99, per_page=50)

        self.assertEqual(respuesta["results"], [])
        self.assertEqual(respuesta["page"], 99)
        self.assertGreaterEqual(respuesta["total"], 1)

    def test_sin_resultados_la_forma_de_la_respuesta_no_cambia(self):
        """Quien consume no debería tener que contemplar dos formas distintas."""
        respuesta = self._buscar(filters={"res_id": 999999})

        self.assertEqual(respuesta["results"], [])
        self.assertEqual(respuesta["total"], 0)
        self.assertEqual(respuesta["pages"], 0)

    # ==================================================================
    # 4. Orden
    # ==================================================================
    def test_ordena_por_fecha_descendente(self):
        """Lo más reciente primero: es lo que espera quien audita."""
        viejo = self._crear_evento("2026-08-10 08:00:00")
        nuevo = self._crear_evento("2026-08-10 20:00:00")
        medio = self._crear_evento("2026-08-10 14:00:00")

        respuesta = self._buscar()

        self.assertEqual(self._ids(respuesta)[:3], [nuevo.id, medio.id, viejo.id])

    def test_el_orden_es_estable_entre_consultas_iguales(self):
        """Con marcas de tiempo idénticas, el orden no puede variar.

        Varios eventos pueden caer en el mismo segundo (el ciclo de vida de un
        registro suele ocurrir dentro de uno solo). Sin un desempate
        determinístico, PostgreSQL puede devolverlos en distinto orden en cada
        consulta y la paginación deja de ser confiable.
        """
        for _ in range(5):
            self._crear_evento("2026-08-10 12:00:00")

        primera = self._ids(self._buscar())
        segunda = self._ids(self._buscar())

        self.assertEqual(primera, segunda)

    # ==================================================================
    # 5. Errores
    # ==================================================================
    # El criterio de fondo: preguntar mal NUNCA puede verse igual que "no hay
    # nada". Si alguien filtra por action="modificacion" y recibe cero
    # resultados, concluye que no pasó nada — cuando en realidad preguntó mal.

    def test_una_clave_de_filtro_desconocida_es_un_error(self):
        with self.assertRaises(ValidationError):
            self.Evento.search_events(filters={"usuario": 1})

    def test_un_tipo_de_accion_inexistente_es_un_error(self):
        """El caso que motiva toda esta sección: el valor en español."""
        with self.assertRaises(ValidationError):
            self.Evento.search_events(filters={"action": "modificacion"})

    def test_un_modelo_inexistente_es_un_error(self):
        with self.assertRaises(ValidationError):
            self.Evento.search_events(filters={"model": "res.no.existe"})

    def test_una_fecha_con_formato_invalido_es_un_error(self):
        with self.assertRaises(ValidationError):
            self.Evento.search_events(filters={"date_from": "15/08/2026"})

    def test_un_rango_de_fechas_invertido_es_un_error(self):
        with self.assertRaises(ValidationError):
            self.Evento.search_events(filters={
                "date_from": "2026-08-15", "date_to": "2026-08-01"})

    def test_una_zona_horaria_desconocida_es_un_error(self):
        with self.assertRaises(ValidationError):
            self.Evento.search_events(filters={
                "date_from": "2026-08-15", "tz": "America/Nowhere"})

    def test_una_pagina_menor_a_uno_es_un_error(self):
        with self.assertRaises(ValidationError):
            self.Evento.search_events(page=0)

    def test_pedir_mas_del_techo_por_pagina_es_un_error(self):
        """No se recorta en silencio: se avisa.

        Sin techo, una consulta sin filtros sobre millones de eventos intenta
        materializarlos en memoria y degrada el ERP para todos.
        """
        with self.assertRaises(ValidationError):
            self.Evento.search_events(per_page=501)

    # ==================================================================
    # 6. Forma de la respuesta
    # ==================================================================
    def test_la_respuesta_trae_los_metadatos_de_paginacion(self):
        self._crear_evento("2026-08-10 12:00:00")

        respuesta = self._buscar(page=1, per_page=25)

        for clave in ("results", "total", "page", "pages", "per_page"):
            self.assertIn(clave, respuesta, f"Falta «{clave}» en la respuesta.")
        self.assertEqual(respuesta["page"], 1)
        self.assertEqual(respuesta["per_page"], 25)

    def test_cada_evento_trae_los_campos_del_contrato(self):
        """Incluye el detalle de cambios y el nombre congelado del registro."""
        self._crear_evento(
            "2026-08-10 12:00:00", res_id=42, res_name="Cliente Demo",
            cambios={"phone": {"old": "3564-100000", "new": "3564-200000"}},
        )

        evento = self._buscar(filters={"res_id": 42})["results"][0]

        for clave in ("id", "timestamp", "user_id", "user_name", "model",
                      "res_id", "res_name", "action", "changes", "company_id"):
            self.assertIn(clave, evento, f"Falta «{clave}» en el evento.")
        self.assertEqual(evento["res_name"], "Cliente Demo")
        self.assertEqual(evento["changes"]["phone"]["new"], "3564-200000")
