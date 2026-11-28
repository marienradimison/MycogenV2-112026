from datetime import timedelta
from pathlib import Path

from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.conf import settings
from django.http import FileResponse, Http404
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from django import forms

from .crud import REGISTRY, Crud, related_tables
from .forms import LimsModelForm, lims_formfield
from .models import ActivityLog, AnalysisCode, Facility, Patient, Room, Sample

facility_crud = Crud(
    Facility, "facility",
    fields=["code", "name", "type", "region", "district", "contact", "active", "notes"],
    list_display=["code", "name", "type", "region", "district", "active"],
    search_fields=["code", "name", "region", "district"],
    list_filter=["region", "type", "active"],
    ordering=["region", "code"],
    icon="bi-hospital", group="Référentiels",
    header_links=[("Plan de masse", "core:floorplan", "bi-map")],
)

room_crud = Crud(
    Room, "room",
    fields=["number", "name", "zone", "usage", "responsible", "phone_ext", "area_m2", "access", "active", "notes"],
    list_display=["number", "name", "zone", "usage", "responsible", "phone_ext", "active"],
    search_fields=["number", "name", "zone", "access"],
    list_filter=["usage", "active"],
    icon="bi-door-open", group="Administration",
    header_links=[("Plan de masse", "core:floorplan", "bi-map")],
    extra_context=lambda obj, request: {"plan_url": f"/plan-de-masse/?salle={obj.number}"},
)

code_crud = Crud(
    AnalysisCode, "code",
    fields=["category", "code", "meaning", "kind", "method", "scope", "group", "order", "requestable", "active"],
    list_display=["code", "meaning", "category", "kind", "method", "scope", "group", "active"],
    search_fields=["code", "meaning"],
    list_filter=["category", "kind", "active"],
    ordering=["order", "code"],
    icon="bi-book", group="Administration",
)

patient_crud = Crud(
    Patient, "patient",
    fields=["last_name", "first_name", "sex", "birth_date", "age_years", "national_id",
            "tb_register_number", "phone", "address", "district", "region", "hiv_status",
            "tb_history", "notes"],
    list_display=["code", "last_name", "first_name", "sex", "age", "district", "hiv_status", "tb_history"],
    search_fields=["code", "last_name", "first_name", "national_id", "tb_register_number", "phone"],
    list_filter=["sex", "hiv_status", "tb_history", "research_consent"],
    icon="bi-person-vcard", group="CNRM",
)

class SampleForm(LimsModelForm):
    """Modification d'un échantillon (l'enregistrement se fait par l'assistant « Enregistrer »)."""

    requested_analyses = forms.MultipleChoiceField(label="Analyses demandées", required=False,
                                                   choices=[], widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        from .register import analysis_choices
        super().__init__(*args, **kwargs)
        self.fields["requested_analyses"].choices = analysis_choices(self.instance)

    class Meta:
        model = Sample
        fields = ["patient", "facility", "requester", "requester_contact", "host", "sample_type", "type_detail", "aspect", "volume_ml",
                  "collected_at", "received_at", "reason", "followup_month", "project", "study", "case",
                  "case_text", "external_id", "requested_analyses", "conform", "non_conformity", "notes"]
        formfield_callback = lims_formfield


from .sample_export import export_samples  # noqa: E402


def sample_context(obj, request):
    from .analyses import sample_analyses
    from .validation import summarize

    analyses = sample_analyses(obj, request.user)
    for a in analyses:
        a["rows"] = [{"obj": r, "summary": summarize(r)} for r in a["results"]]
    shown = {"genexperttest", "microscopy", "culture", "dst", "npoctest", "quantiferon"}
    return {"analyses": analyses, "patient": obj.patient,
            "other_related": [t for t in related_tables(obj, request.user)
                              if t["crud"].model._meta.model_name not in shown and t["rows"]]}


sample_crud = Crud(
    Sample, "sample",
    fields=SampleForm.Meta.fields,
    form_class=SampleForm,
    list_display=[("code", "N° échantillon"), ("patient__full_name", "Patient"),
                  ("patient__code", "Identifiant externe"), ("type_display", "Type de prélèvement"),
                  ("facility__name", "Provenance / CDT"), ("received_at", "Date de réception"),
                  ("project__code", "Projet"), ("study__code", "Étude"), ("case_display", "Cas"), "status"],
    search_fields=["code", "external_id", "patient__code", "patient__last_name", "patient__first_name",
                   "facility__name", "facility__code"],
    list_filter=["sample_type", "status", "project"],
    icon="bi-droplet", group="CNRM",
    detail_template="core/sample_detail.html",
    extra_context=sample_context,
    exclude_urls=("create", "update"),
    create_url="core:register",
    update_url="core:register_edit",
    exporter=export_samples,
    hidden_filters=["patient"],   # « tous les échantillons de ce patient » depuis une fiche
)


@login_required
def dashboard(request):
    from apps.diagnostic.models import DST, Culture, GeneXpertTest, Microscopy, NPOCTest, Quantiferon
    from apps.feed import news

    from .validation import with_results

    today = timezone.localdate()
    start_week = today - timedelta(days=today.weekday())
    year_start = today.replace(month=1, day=1)

    xpert_year = GeneXpertTest.objects.filter(test_date__gte=year_start)
    xpert_pos = xpert_year.exclude(mtb_result__in=["NOT_DETECTED", "INVALID", "ERROR", "NO_RESULT"])
    rr = xpert_year.filter(rif_result="DETECTED").count()
    micro_year = Microscopy.objects.filter(test_date__gte=year_start)
    micro_pos = micro_year.filter(grade__in=["SCANTY", "1+", "2+", "3+"])

    if settings.NEWS_AUTO_FETCH:
        news.refresh_in_background()

    # échantillons reçus par jour sur 30 jours
    days = [today - timedelta(days=i) for i in range(29, -1, -1)]
    counts = dict(
        Sample.objects.filter(received_at__date__gte=days[0])
        .values_list("received_at__date").annotate(n=Count("id")).values_list("received_at__date", "n")
    )
    pending = []
    for model in (GeneXpertTest, NPOCTest, Microscopy, Culture, DST, Quantiferon):
        n = with_results(model.objects.filter(result_status="DRAFT")).count()   # cultures en étuve exclues
        if n:
            pending.append((REGISTRY[model], n))

    ctx = {
        "stats": {
            "samples_today": Sample.objects.filter(received_at__date=today).count(),
            "samples_week": Sample.objects.filter(received_at__date__gte=start_week).count(),
            "samples_open": Sample.objects.filter(status__in=["RECEIVED", "IN_PROGRESS"]).count(),
            "patients": Patient.objects.count(),
            "xpert_year": xpert_year.count(),
            "xpert_pos": xpert_pos.count(),
            "rr": rr,
            "cultures_running": Culture.objects.filter(result="PENDING").count(),
            "micro_year": micro_year.count(),
            "micro_pos": micro_pos.count(),
            "micro_today": Microscopy.objects.filter(test_date=today).count(),
            "micro_fm": micro_year.filter(method="FM").count(),
            "micro_zn": micro_year.filter(method="ZN").count(),
        },
        "chart_labels": [d.strftime("%d/%m") for d in days],
        "chart_values": [counts.get(d, 0) for d in days],
        "pending": pending,
        "news": news.current_articles(),
    }
    from apps.feed.models import Highlight
    from apps.feed.views import decorate, posts_queryset
    highlight = Highlight.objects.filter(current=True).select_related("post", "post__author").first()
    ctx["highlight"] = highlight
    if highlight and highlight.post_id and highlight.post.kind in ("POLL", "CHALLENGE"):
        # sondage / challenge : on vote et on répond directement depuis « À la une »
        ctx["une_post"] = decorate(list(posts_queryset(request.user).filter(pk=highlight.post_id)), request.user)[0]
    return render(request, "core/dashboard.html", ctx)


@login_required
def module_home(request, key):
    """Page d'accueil d'un module : tuiles de ses sous-modules (selon les droits de l'utilisateur)."""
    from .menu import module
    entry = module(request.user, key)
    if entry is None or not entry["items"]:
        raise Http404
    return render(request, "core/module_home.html", {"module": entry})


@login_required
def search(request):
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        for crud in REGISTRY.values():
            if not crud.search_fields or not request.user.has_perm(crud.perm("view")):
                continue
            cond = Q()
            for f in crud.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            hits = list(crud.model.objects.filter(cond)[:10])
            if hits:
                results.append((crud, hits))
    return render(request, "core/search.html", {"q": q, "results": results})


@login_required
@xframe_options_sameorigin   # PDF affichés dans les pages MYCOGEN (MycoLearn, documents qualité)
def protected_media(request, path):
    """Fichiers téléversés (rapports…) : accessibles uniquement aux utilisateurs connectés."""
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise Http404
    # Seuls images et PDF s'affichent dans le navigateur ; tout autre fichier (HTML, SVG, scripts…) est
    # téléchargé, pour qu'un fichier téléversé ne puisse pas exécuter de code dans la session de l'utilisateur.
    inline = target.suffix.lower() in INLINE_MEDIA
    ranged = range_response(request, target)       # lecture vidéo / audio : avance rapide et reprise
    if ranged is not None:
        return ranged
    resp = FileResponse(open(target, "rb"), as_attachment=not inline, filename=target.name)
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Accept-Ranges"] = "bytes"
    return resp


INLINE_MEDIA = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".pdf",
                ".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v", ".mp3", ".m4a", ".wav", ".aac", ".oga", ".opus"}
STREAMED_MEDIA = {".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v", ".mp3", ".m4a", ".wav", ".aac", ".oga", ".opus"}
RANGE_CHUNK = 4 * 1024 * 1024


def range_response(request, target):
    """Réponse 206 (une seule plage d'octets) pour les fichiers audio / vidéo, sinon None."""
    import mimetypes
    import re

    from django.http import HttpResponse, StreamingHttpResponse

    header = request.headers.get("Range", "")
    if target.suffix.lower() not in STREAMED_MEDIA or not header:
        return None
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    size = target.stat().st_size
    if not m or (not m.group(1) and not m.group(2)):
        return None
    if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    else:                                           # « bytes=-500 » : les 500 derniers octets
        start, end = max(size - int(m.group(2)), 0), size - 1
    if start >= size or start > end:
        resp = HttpResponse(status=416)
        resp["Content-Range"] = f"bytes */{size}"
        return resp
    length = end - start + 1

    def chunks():
        with open(target, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                data = f.read(min(RANGE_CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    resp = StreamingHttpResponse(chunks(), status=206,
                                 content_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")
    resp["Content-Range"] = f"bytes {start}-{end}/{size}"
    resp["Content-Length"] = str(length)
    resp["Accept-Ranges"] = "bytes"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
@permission_required("core.view_activitylog", raise_exception=True)
def activity(request):
    logs = ActivityLog.objects.select_related("user")[:300]
    return render(request, "core/activity.html", {"logs": logs})
