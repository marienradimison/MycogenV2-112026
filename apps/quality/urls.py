from django.urls import path

from . import views

app_name = "quality"

urlpatterns = [
    path("", views.monitoring, name="monitoring"),
    *[url for crud in views.CRUDS for url in crud.urls()],
]
