from . import views

app_name = "research"

urlpatterns = [url for crud in views.CRUDS for url in crud.urls()]
