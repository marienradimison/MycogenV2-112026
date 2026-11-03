from django.urls import path

from . import views

app_name = "feed"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("etat/", views.state, name="state"),
    path("archives/", views.archive, name="archive"),
    path("publier/", views.create, name="create"),
    path("<int:pk>/supprimer/", views.delete, name="delete"),
    path("<int:pk>/reagir/", views.react, name="react"),
    path("<int:pk>/commenter/", views.comment, name="comment"),
    path("<int:pk>/voter/", views.vote, name="vote"),
    path("<int:pk>/repondre/", views.answer, name="answer"),
    path("<int:pk>/cloturer/", views.close, name="close"),
    path("commentaire/<int:pk>/supprimer/", views.comment_delete, name="comment_delete"),
]
