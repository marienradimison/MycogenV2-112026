from django.urls import path

from . import views

app_name = "instruments"

urlpatterns = [
    path("", views.monitor, name="monitor"),
    path("messages/", views.message_list, name="message_list"),
    path("messages/<int:pk>/", views.message_detail, name="message_detail"),
    path("messages/<int:pk>/action/", views.message_action, name="message_action"),
    *views.instrument_crud.urls(),
]
