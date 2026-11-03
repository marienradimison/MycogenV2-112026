from . import views

app_name = "biobank"

urlpatterns = [url for crud in views.CRUDS for url in crud.urls()]
