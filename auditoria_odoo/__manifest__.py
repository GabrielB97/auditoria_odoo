{
    "name": "Auditoría de Actividad Odoo",
    "version": "19.0.1.0.0",
    "summary": "Auditoría interna y aprovechamiento de los registros de actividad de Odoo",
    "author": "Gabriel Bula, Giuliano Galván, Nicole Viarengo",
    "website": "https://github.com/GabrielB97/auditoria_odoo",
    "license": "LGPL-3",
    "category": "Tools",
    "depends": ["base", "mail", "web"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "application": True,
    "installable": True,
}
