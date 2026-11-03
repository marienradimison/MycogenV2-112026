from . import views

app_name = "bioinfo"

urlpatterns = [url for crud in views.CRUDS for url in crud.urls()]
