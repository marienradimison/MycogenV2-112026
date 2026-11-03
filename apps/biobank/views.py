from apps.core.crud import Crud

from .models import BiobankItem, Movement, StorageBox, StorageUnit

CRUDS = [
    Crud(
        BiobankItem, "item",
        fields=["item_type", "sample", "parent", "project", "label", "quantity", "unit", "concentration",
                "purity_260_280", "box", "position", "stored_on", "status", "freeze_thaw", "notes"],
        list_display=["code", "item_type", "sample", "label", "project", "quantity", "unit", "location",
                      "status"],
        search_fields=["code", "label", "sample__code", "sample__patient__code", "parent__code"],
        list_filter=["item_type", "status", "project", "box"],
        icon="bi-box-seam",
    ),
    Crud(
        StorageBox, "box",
        fields=["unit", "name", "shelf", "rack", "rows", "cols", "content"],
        list_display=["name", "unit", "shelf", "rack", "content", "occupied", "capacity"],
        search_fields=["name", "content", "unit__name"],
        list_filter=["unit"],
        icon="bi-grid-3x3",
        detail_template="biobank/box_detail.html",
    ),
    Crud(
        StorageUnit, "unit",
        fields=["name", "type", "room", "location", "serial_number", "active", "notes"],
        list_display=["name", "type", "room", "location", "serial_number", "active"],
        search_fields=["name", "location", "serial_number"],
        list_filter=["type", "active"],
        icon="bi-snow",
    ),
    Crud(
        Movement, "movement",
        fields=["item", "type", "date", "quantity", "destination", "reason", "operator"],
        list_display=["date", "item", "type", "quantity", "destination", "reason", "operator"],
        search_fields=["item__code", "destination", "reason"],
        list_filter=["type"],
        icon="bi-arrow-left-right",
    ),
]
