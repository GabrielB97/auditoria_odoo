# auditoria_odoo — Proyecto Final (UTN FRSF)

Módulo nativo de **Odoo 19 Community** para la auditoría interna y el aprovechamiento
de los registros de actividad del ERP.

**Equipo:** Gabriel Bula · Giuliano Galván · Nicole Viarengo — **Tutor:** Ing. David López
La documentación de gestión y de producto está en el vault compartido del equipo.

---

## Entorno de desarrollo local

Requisitos: **Docker** (Docker Desktop en Windows, `docker.io` en Ubuntu) y **Git**.

```bash
git clone git@github.com:GabrielB97/auditoria_odoo.git
cd auditoria_odoo
docker compose up -d
```

Abrir **http://localhost:8169**:

1. Crear la base de datos `tfc_auditoria`
   (*master password*: la definida en `config/odoo.conf`; tildar **datos de demostración**).
2. Activar el **modo desarrollador** → **Apps → Actualizar lista de aplicaciones**.
3. Buscar **auditoria_odoo** → **Instalar**.

### Comandos habituales

| Qué hace | Comando |
|---|---|
| Encender / apagar | `docker compose up -d` / `docker compose stop` |
| Ver estado | `docker compose ps` |
| Ver logs de Odoo | `docker compose logs -f web` |
| Aplicar cambios de código | `docker compose restart web` → en Odoo: *Apps → auditoria_odoo → Actualizar* |
| Correr las pruebas | `docker compose run --rm web odoo -d tfc_auditoria -u auditoria_odoo --test-enable --test-tags /auditoria_odoo --stop-after-init` |
| Empezar de cero (borra la BD local) | `docker compose down -v && docker compose up -d` |

> El código viaja por Git; **la base de datos no**. Cada integrante tiene su propio
> laboratorio con sus propios datos de prueba.

⚠️ Para las pruebas hay que usar `run`, **no `exec`**: dentro del contenedor en marcha
el servidor ya ocupa el puerto 8069 y un segundo proceso de Odoo no puede levantar.
Y **sin `--no-http`**, porque las pruebas del endpoint REST necesitan un servidor
HTTP de verdad para hacerse peticiones a sí mismas.

---

## API de consulta de eventos

Los eventos registrados se consultan por HTTP o desde código Odoo.

```bash
# 1. Autenticarse (guarda la sesión)
curl -c cookies.txt -X POST http://localhost:8169/web/session/authenticate \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","params":{"db":"tfc_auditoria","login":"USUARIO","password":"CLAVE"}}'

# 2. Consultar
curl -b cookies.txt \
  "http://localhost:8169/api/auditoria/eventos?model=res.partner&action=write&per_page=10"
```

```python
# Desde dentro de Odoo
env['activity.event'].search_events(
    filters={'model': 'res.partner', 'action': 'write'}, page=1, per_page=50)
```

**Filtros:** `user_id` · `model` · `action` (`create`/`write`/`unlink`/`read`/`confirm`) ·
`res_id` · `date_from` · `date_to` · `tz`. Se combinan con Y lógico.

Las fechas se interpretan en la zona horaria del usuario; los resultados vuelven en **UTC**.
Un filtro o valor inválido devuelve **400 con el motivo** — nunca una lista vacía, porque en
auditoría "no hay eventos" y "preguntaste mal" no pueden verse igual.

> Tras instalar o actualizar el módulo hay que **reiniciar el servidor** (`docker compose
> restart web`) o el endpoint responderá 404: Odoo registra las rutas HTTP al arrancar.

La guía completa de consumo y el contrato de la API están en el vault del equipo.

---

## Estructura

```
auditoria_odoo/          módulo Odoo
├── models/              modelos de datos (activity.event, audit.*)
├── controllers/         endpoints REST / JSON-RPC (capa de APIs)
├── security/            permisos de acceso
├── views/               vistas XML
├── data/                datos semilla
└── tests/               pruebas unitarias
config/odoo.conf         configuración del lab local
docker-compose.yml       entorno local (Odoo 19 + PostgreSQL 16)
```

## Trabajo en equipo

**Una rama por historia de usuario**, partiendo siempre de `dev`:

```bash
git checkout dev && git pull origin dev
git checkout -b h3-permisos
# ... desarrollar y probar ...
git add -A && git commit -m "H3: descripción del cambio"
git push -u origin h3-permisos
```

Luego abrir un **Pull Request hacia `dev`** — ⚠️ GitHub propone `main` por defecto,
hay que cambiarlo. Se integra tras la **revisión de pares**, según la *Definition of
Done* del proyecto.

`main` está **protegida** y contiene sólo lo estable: recibe los cambios desde `dev`
al cierre de cada sprint. El detalle del flujo está en [CONTRIBUTING.md](CONTRIBUTING.md).

> Antes de cambiar de computadora: **commit + push**. Lo que no se sube, no viaja.
