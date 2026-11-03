from datetime import timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from apps.core.crud import Crud
from apps.core.forms import LimsModelForm, lims_formfield

from .models import SOON_DAYS, Equipment, RoomAccess


class AccessForm(LimsModelForm):
    class Meta:
        model = RoomAccess
        fields = ["room", "user", "person_name", "function", "level", "granted_on", "expires_on",
                  "training_on", "granted_by", "revoked", "notes"]
        formfield_callback = lims_formfield


CRUDS = [
    Crud(
        Equipment, "equipment",
        fields=["room", "name", "category", "inventory_number", "brand", "model_name", "serial_number", "status",
                "critical", "commissioned_on", "responsible", "supplier", "maintenance_interval_months",
                "last_maintenance", "next_maintenance", "calibration_interval_months", "last_calibration",
                "next_calibration", "notes"],
        list_display=["name", "room", "category", "inventory_number", "status", "next_maintenance",
                      "next_calibration", "responsible"],
        search_fields=["name", "inventory_number", "serial_number", "brand", "model_name", "room__number"],
        list_filter=["status", "category", "room", "critical"],
        icon="bi-tools",
        header_links=[("Surveillance", "quality:monitoring", "bi-shield-check")],
    ),
    Crud(
        RoomAccess, "access",
        fields=AccessForm.Meta.fields,
        form_class=AccessForm,
        list_display=[("person", "Personne"), "room", "function", "level", "granted_on", "expires_on",
                      "training_on", "revoked"],
        search_fields=["user__last_name", "user__first_name", "user__username", "person_name", "function",
                       "room__number", "room__name"],
        list_filter=["room", "level", "revoked"],
        icon="bi-person-badge",
        header_links=[("Surveillance", "quality:monitoring", "bi-shield-check")],
    ),
]


@login_required
@permission_required("quality.view_equipment", raise_exception=True)
def monitoring(request):
    """Tableau de surveillance du responsable matériel et qualité."""
    today = timezone.localdate()
    soon = today + timedelta(days=SOON_DAYS)
    eq = Equipment.objects.exclude(status="RETIRED").select_related("room", "responsible")
    acc = RoomAccess.objects.filter(revoked=False).select_related("room", "user")
    sections = [
        ("danger", "bi-exclamation-octagon", "Matériels en panne ou hors usage",
         eq.filter(status__in=["DOWN", "QUARANTINE"]), "equipment"),
        ("danger", "bi-wrench-adjustable", "Maintenances en retard", eq.filter(next_maintenance__lt=today), "equipment"),
        ("danger", "bi-rulers", "Étalonnages / qualifications en retard", eq.filter(next_calibration__lt=today), "equipment"),
        ("warning", "bi-calendar-event", f"Maintenances dans les {SOON_DAYS} jours",
         eq.filter(next_maintenance__gte=today, next_maintenance__lte=soon), "equipment"),
        ("warning", "bi-calendar-check", f"Étalonnages dans les {SOON_DAYS} jours",
         eq.filter(next_calibration__gte=today, next_calibration__lte=soon), "equipment"),
        ("warning", "bi-gear", "Matériels en maintenance", eq.filter(status="MAINT"), "equipment"),
        ("danger", "bi-person-x", "Accès expirés (non révoqués)", acc.filter(expires_on__lt=today), "access"),
        ("warning", "bi-person-exclamation", f"Accès expirant dans les {SOON_DAYS} jours",
         acc.filter(expires_on__gte=today, expires_on__lte=soon), "access"),
        ("info", "bi-mortarboard", "Accès sans formation enregistrée", acc.filter(training_on__isnull=True), "access"),
        ("info", "bi-question-circle", "Matériels critiques sans échéance de maintenance",
         eq.filter(critical=True, next_maintenance__isnull=True), "equipment"),
    ]
    from apps.diagnostic.models import TemperatureLog
    temps = [t for t in TemperatureLog.objects.filter(measured_at__gte=timezone.now() - timedelta(days=7))
             .select_related("incubator", "incubator__room") if t.out_of_range]
    sections.insert(3, ("danger", "bi-thermometer-high", "Températures d'étuve hors plage (7 jours)", temps, "temperature"))
    sections = [(lvl, icon, title, list(qs[:200]), kind) for lvl, icon, title, qs, kind in sections]  # noqa: E501
    from apps.core.models import Room
    rooms = Room.objects.filter(active=True).order_by("number")
    stats = {
        "equipment": eq.count(), "ok": eq.filter(status="OK").count(),
        "alerts": sum(len(rows) for lvl, _, _, rows, _ in sections if lvl == "danger"),
        "accesses": acc.filter(Q(expires_on__isnull=True) | Q(expires_on__gte=today)).count(),
        "rooms_without_access": rooms.exclude(accesses__revoked=False).count(),
    }
    return render(request, "quality/monitoring.html", {"sections": sections, "stats": stats, "today": today})
