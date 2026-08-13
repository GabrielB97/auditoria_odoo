# -*- coding: utf-8 -*-
{
    "name": "Auditoría de Actividad Odoo",
    "version": "19.0.1.1.0",
    "summary": "Auditoría interna y aprovechamiento de los registros de actividad del ERP",
    "author": "Gabriel Bula, Giuliano Galván, Nicole Viarengo",
    "website": "https://github.com/GabrielB97/auditoria_odoo",
    "license": "LGPL-3",
    "category": "Tools",
    # `base` alcanza para la capa de eventos; `mail` se usará más adelante
    # (chatter y notificaciones del motor de auditorías).
    "depends": ["base", "mail"],
    "data": [
        # El orden importa: primero los permisos, después los datos que crean
        # registros, y al final las vistas que los muestran.
        "security/ir.model.access.csv",
        "data/activity_event_config_data.xml",
        "views/activity_event_views.xml",
    ],
    "application": True,
    "installable": True,
}
