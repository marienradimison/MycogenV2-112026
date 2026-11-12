"""Culture LJ : ensemencement, suivi en étuve, lecture hebdomadaire, retraitement, températures.

Règles de lecture (CNRM) :
- pas de pousse au-delà de 90 jours                    → culture négative (sortie)
- pousse macroscopique → test SD (MPT64) positif       → CMTB, culture positive (sortie, rendu)
- pousse macroscopique → test SD négatif               → non CMTB → identification par LPA
- les deux tubes contaminés                            → tubes jetés, échantillon à retraiter
- un seul tube contaminé                               → tube jeté (date notée), l'autre reste en étuve
"""
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.crud import log
from apps.core.forms import BootstrapFormMixin
from apps.core.models import Sample
from apps.core.pdf import render_document

from .models import Culture, CultureTube, IncubatorReading, ReadingEntry, TemperatureLog

LJ_CODE = "Cult-LJ"


def lj_tabs(active):
    items = [
        ("home", "En étuve", "bi-thermometer-sun", "diagnostic:lj_home"),
        ("inoculation", "Ensemencement", "bi-plus-circle", "diagnostic:lj_inoculation"),
        ("reading", "Lecture étuve", "bi-clipboard2-check", "diagnostic:lj_reading_new"),
        ("history", "Fiches de lecture", "bi-journal-text", "diagnostic:lj_readings"),
        ("retreatment", "Retraitement", "bi-arrow-repeat", "diagnostic:lj_retreatment"),
        ("temperature", "Températures", "bi-thermometer-half", "diagnostic:lj_temperatures"),
    ]
    tabs = [(k, label, icon, reverse(url), k == active) for k, label, icon, url in items]
    tabs.append(("results", "Résultats LJ", "bi-list-ul", reverse("diagnostic:culture_list") + "?medium=LJ",
                 active == "results"))
    return tabs


def incubators():
    from apps.quality.models import Equipment
    return Equipment.objects.filter(category="INCUB").exclude(status="RETIRED").select_related("room")


AGE_FILTERS = [("", "Toutes les cultures"), ("90", "90 jours et plus"),
               ("90s", "90 jours et plus à la fin de la semaine")]
SHEET_ROWS = 24  # lignes par page de la fiche MYC-FIC-008


def age_reference(filtre, date):
    """Date à laquelle l'âge est apprécié : fin de la semaine de lecture (dimanche) ou date de lecture."""
    return date + timedelta(days=6 - date.weekday()) if filtre == "90s" else date


def filter_by_age(cultures, filtre, date):
    if filtre not in ("90", "90s"):
        return cultures
    ref = age_reference(filtre, date)
    return [c for c in cultures if (ref - c.inoculated_on).days >= Culture.NEGATIVE_AFTER_DAYS]


def reading_date(value):
    try:
        return timezone.datetime.strptime(value or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def sheet_pages(rows):
    """Fiche MYC-FIC-008 : pages de 24 lignes, complétées par des lignes vides."""
    pages = [rows[i:i + SHEET_ROWS] for i in range(0, len(rows), SHEET_ROWS)] or [[]]
    return [page + [None] * (SHEET_ROWS - len(page)) for page in pages]


def in_incubator():
    return (Culture.objects.filter(medium="LJ", result="PENDING")
            .select_related("sample", "sample__patient", "incubator").prefetch_related("tubes")
            .order_by("inoculated_on", "sample__code"))


# ---------------------------------------------------------------------------
# Règles
# ---------------------------------------------------------------------------

@transaction.atomic
def set_colonies(culture, colonies):
    """Reporte le comptage sur la culture : 100 / 200 / 300 valent 1+ / 2+ / 3+, sinon nombre exact de colonies."""
    if not colonies or colonies == "0":
        return
    n = int(colonies)
    if n in (100, 200, 300):
        culture.lj_grade, culture.colony_count = f"{n // 100}+", None
    else:
        culture.lj_grade = "1-19" if n < 20 else "1+" if n < 100 else "2+" if n < 200 else "3+"
        culture.colony_count = n


def sheet_fields(post, pk):
    """Champs de la fiche de lecture d'un échantillon, à partir du formulaire."""
    colonies = post.get(f"colonies_{pk}", "").strip()
    if not (colonies.isdigit() and int(colonies) <= 32767):
        colonies = ""
    picked = post.getlist(f"morph_{pk}")
    return {
        "colonies": str(int(colonies)) if colonies else "",
        "morphology": "".join(v for v, _ in ReadingEntry.MORPHOLOGY if v in picked),
        "pigment": post.get(f"pigment_{pk}", "").strip()[:60],
        "baar_aspect": post.get(f"baar_{pk}", "").strip()[:80],
        "sd_control": post.get(f"sdc_{pk}", "") if post.get(f"sdc_{pk}") in ("+", "-") else "",
        "conclusion": post.get(f"conclusion_{pk}", "") if post.get(f"conclusion_{pk}") in ("CMTB", "ATYP") else "",
        "cj_lj": post.get(f"cjlj_{pk}") == "on",
        "cj_pyr": post.get(f"cjpyr_{pk}") == "on",
    }


def apply_reading(culture, obs, sd, date, confirm_negative, user, negative_ref=None, colonies=""):
    """Applique les observations d'une lecture à une culture. obs = {n° tube: observation}.
    negative_ref : date à laquelle l'âge de 90 jours est apprécié (par défaut la date de lecture).
    Retourne (action, tubes jetés)."""
    tubes = {t.number: t for t in culture.tubes.all()}
    discarded = []
    for n, tube in tubes.items():
        o = obs.get(n, "")
        if not tube.active or not o:
            continue
        if o == "CONTAMINATED":
            tube.status, tube.status_date = "CONTAMINATED", date
            discarded.append(n)
        elif o == "GROWTH":
            tube.status, tube.status_date = "GROWTH", date
            culture.growth_on = culture.growth_on or date
        tube.save()
    active = [t for t in tubes.values() if t.active]
    growth = any(t.status == "GROWTH" for t in active) or bool(culture.growth_on and active)

    def exit_tubes():
        for t in active:
            t.status, t.status_date = "EXITED", date
            t.save()

    action = "TUBE_DISCARDED" if discarded else "NONE"
    if not active:  # tous les tubes contaminés
        culture.result, culture.result_date, culture.retreat_status = "CONTAMINATED", date, "TO_RETREAT"
        action = "RETREAT"
    elif growth:
        set_colonies(culture, colonies)
        if sd in ("POS", "NEG"):
            culture.sd_test, culture.sd_date = sd, date
            culture.result, culture.result_date = "POSITIVE", date
            if sd == "POS":
                culture.identification, culture.id_method = "MTBC", "Test SD (MPT64) positif"
                action = "POSITIVE"
            else:
                culture.identification, culture.id_method = "NON_MTBC", "Test SD (MPT64) négatif → LPA"
                action = "NON_MTBC"
            exit_tubes()
        else:
            action = "GROWTH_SD"
    elif confirm_negative and ((negative_ref or date) - culture.inoculated_on).days >= Culture.NEGATIVE_AFTER_DAYS:
        culture.result, culture.result_date = "NEGATIVE", date
        exit_tubes()
        action = "NEGATIVE"
    culture.updated_by = user
    culture.save()
    if action not in ("NONE", "TUBE_DISCARDED"):
        log(user, "UPDATE", culture, {"lecture étuve": dict(ReadingEntry.ACTIONS)[action]})
    return action, discarded


# ---------------------------------------------------------------------------
# Vues
# ---------------------------------------------------------------------------

def lpa_pending():
    """Cultures non CMTB dont l'identification LPA n'est pas encore saisie."""
    from apps.research.models import LPATest
    rows = Culture.objects.filter(medium="LJ", identification="NON_MTBC").select_related("sample", "sample__patient")
    out = []
    for c in rows:
        has_lpa = LPATest.objects.filter(sample=c.sample, test_date__gte=c.sd_date or c.inoculated_on).exists()
        out.append({"culture": c, "has_lpa": has_lpa,
                    "lpa_url": reverse("research:lpa_create") + f"?sample={c.sample_id}&kit=CMAS&source=CULTURE"})
    return out


@login_required
@permission_required("diagnostic.view_culture", raise_exception=True)
def lj_home(request):
    cultures = list(in_incubator())
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    for c in cultures:
        c.weeks = (c.age_days or 0) // 7
    last_reading = IncubatorReading.objects.first()
    stats = {
        "cultures": len(cultures),
        "tubes": sum(1 for c in cultures for t in c.tubes.all() if t.active),
        "to_exit": sum(1 for c in cultures if c.stage[0] == "EXIT"),
        "sd": sum(1 for c in cultures if c.stage[0] == "SD"),
        "retreat": Culture.objects.filter(medium="LJ", retreat_status="TO_RETREAT").count(),
        "to_inoculate": len(samples_to_inoculate()),
        "read_this_week": bool(last_reading and last_reading.date >= week_start),
    }
    return render(request, "diagnostic/lj_home.html", {
        "tabs": lj_tabs("home"), "cultures": cultures, "stats": stats, "last_reading": last_reading,
        "lpa": lpa_pending(),
        "retreat": Culture.objects.filter(medium="LJ", retreat_status="TO_RETREAT").select_related("sample", "sample__patient"),
        "today": today,
    })


def samples_to_inoculate():
    """Échantillons pour lesquels une culture LJ est demandée mais pas encore ensemencée."""
    qs = (Sample.objects.exclude(status="REJECTED").select_related("patient", "facility")
          .annotate(n_lj=Count("culture_set", filter=Q(culture_set__medium="LJ"))).filter(n_lj=0)
          .order_by("received_at"))
    return [s for s in qs if LJ_CODE in (s.requested_analyses or [])]


class InoculationForm(BootstrapFormMixin, forms.Form):
    inoculated_on = forms.DateField(label="Date d'ensemencement / mise en étuve", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    incubator = forms.ModelChoiceField(label="Étuve", queryset=None, required=False)
    decontamination = forms.ChoiceField(label="Décontamination", choices=Culture.DECONTAMINATION, initial="PETROFF")
    tube_count = forms.TypedChoiceField(label="Nombre de tubes", choices=Culture.TUBE_COUNTS, coerce=int, initial=2,
                                    required=False, empty_value=2)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["incubator"].queryset = incubators()


@login_required
@permission_required("diagnostic.add_culture", raise_exception=True)
def lj_inoculation(request):
    form = InoculationForm(request.POST or None, initial={"inoculated_on": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        created = 0
        with transaction.atomic():
            for sid in request.POST.getlist("samples"):
                sample = Sample.objects.filter(pk=sid).first()
                if sample and not sample.culture_set.filter(medium="LJ").exists():
                    c = Culture.objects.create(sample=sample, medium="LJ", inoculated_on=d["inoculated_on"],
                                               incubator=d["incubator"], decontamination=d["decontamination"], tube_count=d["tube_count"],
                                               performed_by=request.user, test_date=d["inoculated_on"],
                                               created_by=request.user, updated_by=request.user)
                    log(request.user, "CREATE", c)
                    created += 1
            for cid in request.POST.getlist("retreat"):
                old = Culture.objects.filter(pk=cid, retreat_status="TO_RETREAT").first()
                if old:
                    c = Culture.objects.create(sample=old.sample, medium="LJ", inoculated_on=d["inoculated_on"],
                                               incubator=d["incubator"], decontamination=d["decontamination"], tube_count=d["tube_count"],
                                               performed_by=request.user, test_date=d["inoculated_on"],
                                               retreat_of=old, created_by=request.user, updated_by=request.user,
                                               comment=f"Retraitement (culture du {old.inoculated_on:%d/%m/%Y} contaminée)")
                    old.retreat_status = "RETREATED"
                    old.save(update_fields=["retreat_status", "updated_at"])
                    log(request.user, "CREATE", c, {"retraitement de": str(old.pk)})
                    created += 1
        if created:
            messages.success(request, f"{created} culture(s) LJ ensemencée(s) et mise(s) en étuve le {d['inoculated_on']:%d/%m/%Y} — {created * d['tube_count']} tube(s).")
        else:
            messages.warning(request, "Aucun échantillon sélectionné.")
        return redirect("diagnostic:lj_home")
    return render(request, "diagnostic/lj_inoculation.html", {
        "tabs": lj_tabs("inoculation"), "form": form, "samples": samples_to_inoculate(),
        "retreat": Culture.objects.filter(medium="LJ", retreat_status="TO_RETREAT").select_related("sample", "sample__patient"),
        "no_incubator": not incubators().exists(),
    })


@login_required
@permission_required("diagnostic.view_culture", raise_exception=True)
def lj_blank_sheet(request):
    """Fiche de lecture vierge : toutes les cultures en étuve, à remplir devant l'étuve."""
    date = reading_date(request.GET.get("date")) or timezone.localdate()
    cultures = filter_by_age(list(in_incubator()), request.GET.get("filtre", ""), date)
    return render_document(request, "documents/lj_reading.html", {
        "reading": None, "pages": sheet_pages([{"code": c.sample.code} for c in cultures]),
        "back_url": reverse("diagnostic:lj_reading_new")}, f"fiche_lecture_vierge_{timezone.localdate():%Y-%m-%d}.pdf")


@login_required
@permission_required("diagnostic.change_culture", raise_exception=True)
def lj_reading_new(request):
    cultures = list(in_incubator())
    if request.method == "POST":
        date = reading_date(request.POST.get("date"))
        if not date:
            messages.error(request, "Date de lecture invalide.")
            return redirect("diagnostic:lj_reading_new")
        # Seules les cultures affichées (filtre d'âge) font partie de cette lecture
        shown = set(request.POST.getlist("cultures"))
        if shown:
            cultures = [c for c in cultures if str(c.pk) in shown]
        negative_ref = age_reference(request.POST.get("filtre", ""), date)
        with transaction.atomic():
            reading = IncubatorReading.objects.create(
                date=date, operator=request.user, notes=request.POST.get("notes", "")[:2000],
                incubator_id=request.POST.get("incubator") or None)
            for c in cultures:
                obs = {n: request.POST.get(f"t{n}_{c.pk}", "") for n in (1, 2)}
                sd = request.POST.get(f"sd_{c.pk}", "")
                confirm = request.POST.get(f"neg_{c.pk}") == "on"
                age = (date - c.inoculated_on).days
                sheet = sheet_fields(request.POST, c.pk)
                # contrôle du test SD négatif : test invalide, à refaire
                action, discarded = apply_reading(c, obs, "" if sheet["sd_control"] == "-" else sd, date, confirm,
                                                  request.user, negative_ref, sheet["colonies"])
                if action == "NEGATIVE":
                    sheet["colonies"] = "0"
                ReadingEntry.objects.create(reading=reading, culture=c, age_days=max(age, 0), tube1=obs[1],
                                            tube2=obs[2], sd_test=sd, action=action,
                                            discarded_tubes=", ".join(str(n) for n in discarded), **sheet)
        messages.success(request, f"Lecture du {date:%d/%m/%Y} enregistrée ({len(cultures)} cultures).")
        return redirect(reading)
    date = reading_date(request.GET.get("date")) or timezone.localdate()
    filtre = request.GET.get("filtre", "")
    filters = [{"key": k, "label": label, "count": len(filter_by_age(cultures, k, date)), "active": k == filtre}
               for k, label in AGE_FILTERS]
    total = len(cultures)
    cultures = filter_by_age(cultures, filtre, date)
    ref = age_reference(filtre, date)
    previous = {}   # fiche déjà saisie pour une pousse en attente de test SD
    for e in ReadingEntry.objects.filter(culture__in=[c for c in cultures if c.growth_on]).order_by("reading__date", "pk"):
        previous[e.culture_id] = e
    for c in cultures:
        c.active_tubes = {str(t.number): t for t in c.tubes.all()}
        c.prev = previous.get(c.pk)
        c.read_age = (date - c.inoculated_on).days
        c.growth_days = ((c.growth_on if c.growth_on and c.growth_on <= date else date) - c.inoculated_on).days
        c.can_negative = (ref - c.inoculated_on).days >= Culture.NEGATIVE_AFTER_DAYS
        c.suggest_negative = c.can_negative and not c.growth_on
        c.reaches_on = c.inoculated_on + timedelta(days=Culture.NEGATIVE_AFTER_DAYS)
    return render(request, "diagnostic/lj_reading_form.html", {
        "tabs": lj_tabs("reading"), "cultures": cultures, "date": date, "incubators": incubators(),
        "filters": filters, "filtre": filtre, "total": total, "week_end": age_reference("90s", date),
        "morph_choices": ReadingEntry.MORPHOLOGY, "sd_control_choices": ReadingEntry.SD_SIGNS,
        "conclusion_choices": ReadingEntry.CONCLUSIONS, "pigments": ReadingEntry.PIGMENTS,
        "baar_aspects": ReadingEntry.BAAR_ASPECTS,
        "obs_choices": ReadingEntry.OBS[1:], "sd_choices": Culture.SD_RESULTS[1:],
        "growth_min": Culture.GROWTH_MIN_DAYS, "neg_days": Culture.NEGATIVE_AFTER_DAYS,
    })


def sheet_row(entry):
    """Ligne de la fiche MYC-FIC-008."""
    remark = entry.get_action_display()
    if entry.discarded_tubes:
        remark += f" (tube {entry.discarded_tubes} jeté)"
    return {
        "code": entry.culture.sample.code, "colonies": entry.colonies, "morphology": entry.morphology,
        "pigment": entry.pigment, "baar": entry.baar_aspect, "growth_time": f"{entry.growth_days} j",
        "sd_c": entry.control_sign, "sd_t": entry.sd_sign, "conclusion": entry.get_conclusion_display(),
        "lj": "X" if entry.cj_lj else "", "pyr": "X" if entry.cj_pyr else "", "remark": remark,
        "url": entry.culture.get_absolute_url(),
    }


def reading_sections(reading):
    entries = list(reading.entries.select_related("culture", "culture__sample", "culture__sample__patient"))
    groups = [
        ("NEGATIVE", "Cultures négatives (≥ 90 j sans pousse)", "neg"),
        ("POSITIVE", "Cultures positives — CMTB (test SD positif)", "pos"),
        ("NON_MTBC", "Non CMTB (test SD négatif) — identification LPA", "lpa"),
        ("GROWTH_SD", "Pousses — test SD à réaliser", "sd"),
        ("RETREAT", "Cultures contaminées (2 tubes) — à retraiter", "retreat"),
    ]
    sections = [(title, cls, [e for e in entries if e.action == code]) for code, title, cls in groups]
    discarded = [e for e in entries if e.discarded_tubes]
    remaining = [e for e in entries if e.action in ("NONE", "TUBE_DISCARDED")]
    return entries, sections, discarded, remaining


@login_required
@permission_required("diagnostic.view_culture", raise_exception=True)
def lj_reading(request, pk):
    reading = get_object_or_404(IncubatorReading.objects.select_related("operator", "incubator"), pk=pk)
    entries, sections, discarded, remaining = reading_sections(reading)
    ctx = {"reading": reading, "entries": entries, "sections": sections, "discarded": discarded,
           "remaining": remaining, "tabs": lj_tabs("history"), "project_label": "Culture LJ",
           "back_url": reverse("diagnostic:lj_readings"), "now": timezone.now(),
           "sheet_rows": [sheet_row(e) for e in entries]}
    if request.GET.get("print") or request.GET.get("format") == "pdf":
        ctx["pages"] = sheet_pages([sheet_row(e) for e in entries])
        return render_document(request, "documents/lj_reading.html", ctx, f"lecture_etuve_{reading.date:%Y-%m-%d}.pdf")
    return render(request, "diagnostic/lj_reading.html", ctx)


@login_required
@permission_required("diagnostic.view_culture", raise_exception=True)
def lj_retreatment(request):
    related = ("sample", "sample__patient", "sample__project", "sample__study", "sample__case")
    retreats = Culture.objects.filter(medium="LJ", retreat_of__isnull=False).select_related(*related)
    by_sample = {}
    for c in retreats.order_by("inoculated_on", "pk"):
        by_sample.setdefault(c.sample_id, []).append(c)
    history = [{"sample": rows[-1].sample, "count": len(rows), "dates": [c.inoculated_on for c in rows],
                "latest": rows[-1]} for rows in by_sample.values()]
    history.sort(key=lambda r: (r["dates"][-1], r["sample"].pk), reverse=True)
    to_retreat = list(Culture.objects.filter(medium="LJ", retreat_status="TO_RETREAT").select_related(*related)
                      .order_by("result_date", "pk"))
    for c in to_retreat:
        c.n_retreated = len(by_sample.get(c.sample_id, []))
    return render(request, "diagnostic/lj_retreatment.html", {
        "tabs": lj_tabs("retreatment"), "to_retreat": to_retreat, "history": history,
    })


@login_required
@permission_required("diagnostic.view_culture", raise_exception=True)
def lj_readings(request):
    readings = IncubatorReading.objects.select_related("operator", "incubator").annotate(
        n=Count("entries"),
        n_pos=Count("entries", filter=Q(entries__action="POSITIVE")),
        n_neg=Count("entries", filter=Q(entries__action="NEGATIVE")),
        n_lpa=Count("entries", filter=Q(entries__action="NON_MTBC")),
        n_retreat=Count("entries", filter=Q(entries__action="RETREAT")),
        n_discarded=Count("entries", filter=~Q(entries__discarded_tubes="")),
    )[:200]
    return render(request, "diagnostic/lj_readings.html", {"tabs": lj_tabs("history"), "readings": readings})


class TemperatureForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = TemperatureLog
        fields = ["incubator", "measured_at", "value", "comment"]
        widgets = {"measured_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["incubator"].queryset = incubators()

    def clean(self):
        d = super().clean()
        v = d.get("value")
        if v is not None and not (TemperatureLog.TARGET_MIN <= v <= TemperatureLog.TARGET_MAX) and not d.get("comment"):
            self.add_error("comment", "Température hors plage (36–38 °C) : indiquez l'action corrective.")
        return d


@login_required
@permission_required("diagnostic.view_temperaturelog", raise_exception=True)
def lj_temperatures(request):
    can_add = request.user.has_perm("diagnostic.add_temperaturelog")
    initial = {"measured_at": timezone.localtime().replace(second=0, microsecond=0)}
    first = incubators().first()
    if first:
        initial["incubator"] = first.pk
    form = TemperatureForm(request.POST or None, initial=initial)
    if request.method == "POST" and can_add and form.is_valid():
        t = form.save(commit=False)
        t.operator = request.user
        t.save()
        messages.success(request, f"Relevé enregistré : {t.value} °C" + (" (hors plage !)" if t.out_of_range else ""))
        return redirect("diagnostic:lj_temperatures")
    since = timezone.now() - timedelta(days=30)
    logs = TemperatureLog.objects.select_related("incubator", "operator")
    chart = {}
    for t in logs.filter(measured_at__gte=since).order_by("measured_at"):
        chart.setdefault(t.incubator.name, []).append({"x": timezone.localtime(t.measured_at).strftime("%Y-%m-%d %H:%M"),
                                                       "y": float(t.value)})
    return render(request, "diagnostic/lj_temperatures.html", {
        "tabs": lj_tabs("temperature"), "form": form, "can_add": can_add, "logs": logs[:100], "chart": chart,
        "no_incubator": not incubators().exists(), "tmin": float(TemperatureLog.TARGET_MIN),
        "tmax": float(TemperatureLog.TARGET_MAX),
        "out_count": sum(1 for t in logs.filter(measured_at__gte=since) if t.out_of_range),
    })
