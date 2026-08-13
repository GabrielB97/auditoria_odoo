# Cómo trabajamos en este repositorio

## ⛔ No se pushea a `main`

`main` es la rama estable: es lo que se muestra al Tutor y en la defensa.
**Nadie escribe en ella directamente.** Los cambios llegan por *merge* desde `dev`,
al cierre de cada sprint.

## Las ramas

| Rama | Qué es | Quién escribe |
|---|---|---|
| `main` | Estable, demostrable | Nadie: sólo *merge* desde `dev` |
| `dev` | Integración de las historias terminadas | Sólo *merge* desde ramas de historia |
| `h1-eventos`, `h2-filtros`, … | Una por historia de usuario | Quien desarrolla esa historia |
| `v1.0.0`, `v1.1.0`, … | 🔒 Fotos congeladas de `main` (punto de retorno) | Nadie |

## El recorrido de una historia

```bash
# 1. Partir de lo último integrado
git checkout dev
git pull origin dev

# 2. Una rama por historia
git checkout -b h2-filtros

# 3. Trabajar y subir
git add -A
git commit -m "H2: filtra eventos por usuario y rango de fechas"
git push -u origin h2-filtros
```

**4. Pull Request hacia `dev`** (⚠️ GitHub propone `main` por defecto: cambialo a `dev`).

**5. Revisión de pares.** No integra quien escribió el código — lo pide la
*Definition of Done* del proyecto.

## Antes de pedir la revisión

- [ ] El módulo instala en una base limpia.
- [ ] Las pruebas pasan:
      `docker compose run --rm web odoo -d <base> -u auditoria_odoo --test-enable --test-tags /auditoria_odoo --stop-after-init`
- [ ] El código está comentado donde la decisión no es evidente.

## Mensajes de commit

Empezar por la historia, en presente, diciendo **qué** cambió:

```
H1: agrega el modelo activity.event con inmutabilidad
H2: filtra eventos por usuario y rango de fechas
```

El *porqué* va en el cuerpo del mensaje, después de una línea en blanco.

## Al cambiar de computadora

**`commit` + `push` antes de irte.** Lo que no se sube, no viaja.

---

📖 La guía completa está en el vault del equipo: *Guía - Flujo de trabajo con Git (ramas y versiones)*.
