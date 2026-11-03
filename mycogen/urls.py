from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core import account as core_account
from apps.core import views as core_views

admin.site.site_header = "MYCOGEN — Administration"
admin.site.site_title = "MYCOGEN"
admin.site.index_title = "Institut Pasteur de Madagascar · Mycobacteria Unit"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("connexion/", auth_views.LoginView.as_view(), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("mot-de-passe/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("mot-de-passe/ok/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("mot-de-passe-oublie/", core_account.reset_request, name="reset_request"),
    path("", include("apps.core.urls")),
    path("media/<path:path>", core_views.protected_media, name="media"),
    path("diagnostic/", include("apps.diagnostic.urls")),
    path("recherche/", include("apps.research.urls")),
    path("biobanque/", include("apps.biobank.urls")),
    path("bioinformatique/", include("apps.bioinfo.urls")),
    path("automates/", include("apps.instruments.urls")),
    path("chaud/", include("apps.feed.urls")),
    path("qualite/", include("apps.quality.urls")),
    path("stock/", include("apps.stock.urls")),
]
