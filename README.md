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
| Correr las pruebas | `docker compose exec web odoo -d tfc_auditoria -u auditoria_odoo --test-enable --stop-after-init` |
| Empezar de cero (borra la BD local) | `docker compose down -v && docker compose up -d` |

> El código viaja por Git; **la base de datos no**. Cada integrante tiene su propio
> laboratorio con sus propios datos de prueba.

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

**Una rama por historia de usuario:**

```bash
git checkout main && git pull
git checkout -b h1-eventos
# ... desarrollar y probar ...
git add -A && git commit -m "H1: descripción del cambio"
git push -u origin h1-eventos
```

Luego abrir un **Pull Request** hacia `main`. Se integra tras la **revisión de pares**,
según la *Definition of Done* del proyecto.

> Antes de cambiar de computadora: **commit + push**. Lo que no se sube, no viaja.
