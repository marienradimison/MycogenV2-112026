from django.urls import path

from . import account, documents, plan, register, validation, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("m/<slug:key>/", views.module_home, name="module"),
    path("recherche-globale/", views.search, name="search"),
    path("journal/", views.activity, name="activity"),
    path("parametres/", account.settings_view, name="settings"),
    path("parametres/<slug:section>/", account.settings_view, name="settings"),
    path("theme/", account.toggle_theme, name="toggle_theme"),
    path("support/", account.support, name="support"),
    path("support/<slug:kind>/<int:pk>/", account.support_action, name="support_action"),
    path("enregistrer/", register.register, name="register"),
    path("enregistrer/patient/", register.patient_lookup, name="patient_lookup"),
    path("sample/<int:pk>/modifier/", register.register_edit, name="register_edit"),
    path("validation/", validation.validation, name="validation"),
    path("sample/<int:pk>/compte-rendu/", documents.result_report, name="sample_report"),
    path("sample/<int:pk>/fiche-paillasse/", documents.bench_sheet, name="bench_sheet"),
    *views.facility_crud.urls(),
    *views.code_crud.urls(),
    *views.room_crud.urls(),
    path("plan-de-masse/", plan.floor_plan, name="floorplan"),
    *views.patient_crud.urls(),
    *views.sample_crud.urls(),
]
