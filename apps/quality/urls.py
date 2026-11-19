from django.urls import path

from . import views

app_name = "quality"

urlpatterns = [
    path("", views.monitoring, name="monitoring"),
    path("sgq/", views.sgq, name="sgq"),
    path("document/<int:pk>/approuver/", views.document_approve, name="document_approve"),
    *[url for crud in views.CRUDS for url in crud.urls()],
]
