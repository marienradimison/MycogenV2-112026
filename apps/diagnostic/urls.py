from django.urls import path

from . import live, lj, views

app_name = "diagnostic"

urlpatterns = [
    path("genexpert/suivi/", live.genexpert_live, name="genexpert_live"),
    path("npoc/suivi/", live.npoc_live, name="npoc_live"),
    path("lj/", lj.lj_home, name="lj_home"),
    path("lj/ensemencement/", lj.lj_inoculation, name="lj_inoculation"),
    path("lj/lecture/", lj.lj_reading_new, name="lj_reading_new"),
    path("lj/lecture/fiche-vierge/", lj.lj_blank_sheet, name="lj_blank_sheet"),
    path("lj/lectures/", lj.lj_readings, name="lj_readings"),
    path("lj/lectures/<int:pk>/", lj.lj_reading, name="lj_reading"),
    path("lj/retraitement/", lj.lj_retreatment, name="lj_retreatment"),
    path("lj/temperatures/", lj.lj_temperatures, name="lj_temperatures"),
    *[url for crud in views.CRUDS for url in crud.urls()],
]
