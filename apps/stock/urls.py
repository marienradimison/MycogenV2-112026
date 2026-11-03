from django.urls import path

from . import views

app_name = "stock"

urlpatterns = [
    path("", views.home, name="home"),
    *[url for crud in views.CRUDS for url in crud.urls()],
]
