from django.urls import path

from . import views

app_name = "biobank"

urlpatterns = [
    path("item/source/", views.source_info, name="source_info"),
    path("box/<int:pk>/etiquette/", views.box_labels, name="box_label"),
    path("box/etiquettes/", views.box_labels, name="box_labels"),
    path("box/<int:pk>/deplacer/", views.box_move, name="box_move"),
    path("inventory/<int:pk>/constats/", views.inventory_save, name="inventory_save"),
    path("inventory/<int:pk>/scan/", views.inventory_scan, name="inventory_scan"),
    path("inventory/<int:pk>/manquants/", views.inventory_missing, name="inventory_missing"),
    path("inventory/<int:pk>/soumettre/", views.inventory_submit, name="inventory_submit"),
    path("inventory/<int:pk>/valider/", views.inventory_validate, name="inventory_validate"),
    path("inventory/<int:pk>/annuler/", views.inventory_cancel, name="inventory_cancel"),
    path("tracabilite/", views.trace, name="trace"),
    path("rapports/", views.reports, name="reports"),
    *[url for crud in views.CRUDS for url in crud.urls()],
]
