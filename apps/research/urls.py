from django.urls import path

from . import mycolearn, views

app_name = "research"

urlpatterns = [
    path("mycolearn/", mycolearn.mycolearn, name="mycolearn"),
    path("learning/<int:pk>/progression/", mycolearn.progress, name="learning_progress"),
    path("learning/<int:pk>/ma-liste/", mycolearn.favorite, name="learning_favorite"),
    path("learning/<int:pk>/termine/", mycolearn.mark_done, name="learning_done"),
    *[url for crud in views.CRUDS for url in crud.urls()],
]
