"""Enregistre tous les modèles Mycogen dans l'admin Django (gestion avancée)."""
from django.apps import apps
from django.contrib import admin

from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, User

from .models import ActivityLog, Room, UserProfile


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "user", "action", "model", "object_repr"]
    list_filter = ["action", "model"]
    search_fields = ["object_repr", "user__username"]
    readonly_fields = [f.name for f in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    fields = ["job_title", "phone", "photo", "theme"]
    verbose_name = "poste et profil"
    verbose_name_plural = "poste et profil"


class MycogenUserAdmin(UserAdmin):
    """Comptes utilisateurs : le poste est un titre (profil) ; les droits viennent des rôles (groupes)."""

    inlines = [ProfileInline]
    list_display = ["username", "last_name", "first_name", "job", "roles", "is_active", "is_staff"]
    list_filter = ["is_active", "is_staff", "groups"]
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("username", "first_name", "last_name", "email",
                                                 "password1", "password2", "groups")}),
    )
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identité", {"fields": ("first_name", "last_name", "email")}),
        ("Rôles (permissions)", {"fields": ("groups", "is_active", "is_staff", "is_superuser")}),
        ("Permissions individuelles (exceptionnel)", {"classes": ("collapse",), "fields": ("user_permissions",)}),
        ("Dates", {"classes": ("collapse",), "fields": ("last_login", "date_joined")}),
    )

    @admin.display(description="poste")
    def job(self, obj):
        p = getattr(obj, "profile", None)
        return p.job_title if p else ""

    @admin.display(description="rôles")
    def roles(self, obj):
        return ", ".join(getattr(getattr(g, "role_code", None), "code", g.name) for g in obj.groups.all())

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        field = super().formfield_for_manytomany(db_field, request, **kwargs)
        if db_field.name == "groups":
            field.label = "Rôles"
            field.help_text = ("Les rôles donnent les permissions (TL, SL, MB, AS, RSR, RQ/CQ, AL). "
                               "Un utilisateur peut en cumuler plusieurs ; ses droits s'additionnent.")
            field.label_from_instance = lambda g: (f"{g.role_code.code} — {g.name}" if hasattr(g, "role_code")
                                                   else g.name)
        return field


admin.site.unregister(User)
admin.site.register(User, MycogenUserAdmin)
Group._meta.verbose_name = "rôle"
Group._meta.verbose_name_plural = "rôles (permissions)"


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    """Attribution des numéros de salle aux emplacements du plan de masse."""
    list_display = ["zone", "number", "name", "usage", "responsible", "phone_ext", "active"]
    list_editable = ["number", "name", "usage", "active"]
    list_display_links = ["zone"]
    list_filter = ["usage", "active"]
    search_fields = ["number", "name", "zone"]
    ordering = ["zone"]


for label in ("core", "diagnostic", "research", "biobank", "bioinfo", "instruments", "feed", "quality", "stock"):
    for model in apps.get_app_config(label).get_models():
        if admin.site.is_registered(model):
            continue
        fields = [f.name for f in model._meta.fields if f.name not in ("id", "created_at", "updated_at")][:7]
        search = [f for f in ("code", "name", "last_name", "run_id", "library_id") if hasattr(model, f)]
        admin.site.register(model, type(f"{model.__name__}Admin", (admin.ModelAdmin,), {
            "list_display": ["__str__"] + fields[:6],
            "search_fields": search,
            "list_per_page": 50,
        }))
