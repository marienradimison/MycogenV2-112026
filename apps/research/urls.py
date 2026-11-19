from django.urls import path

from . import views

app_name = "research"

urlpatterns = [
    path("mycolearn/", views.mycolearn, name="mycolearn"),
    *[url for crud in views.CRUDS for url in crud.urls()],
]
