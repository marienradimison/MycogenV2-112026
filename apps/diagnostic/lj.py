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
        ("temperature", "Températures", "bi-thermometer-half", "diagnostic:lj_temperatures"),
    ]
    tabs = [(k, label, icon, reverse(url), k == active) for k, label, icon, url in items]
    tabs.append(("results", "Résultats LJ", "bi-list-ul", reverse("diagnostic:culture_list") + "?medium=LJ",
                 active == "results"))
    return tabs


def incubators():
    from apps.quality.models import Equipment
    return Equipment.objects.filter(category="INCUB").exclude(status="RETIRED").select_related("room")


def in_incubator():
    return (Culture.objects.filter(medium="LJ", result="PENDING")
            .select_related("sample", "sample__patient", "incubator").prefetch_related("tubes")
            .order_by("inoculated_on", "sample__code"))


# ---------------------------------------------------------------------------
# Règles
# ---------------------------------------------------------------------------

@transaction.atomic
def apply_reading(culture, obs, sd, date, confirm_negative, user):
    """Applique les observations d'une lecture à une culture. obs = {n° tube: observation}.
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
    elif confirm_negative and (date - culture.inoculated_on).days >= Culture.NEGATIVE_AFTER_DAYS:
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
    cultures = list(in_incubator())
    for c in cultures:
        tubes = {t.number: t for t in c.tubes.all()}
        c.sheet_tubes = [tubes.get(1), tubes.get(2)]
    return render_document(request, "documents/lj_reading.html", {
        "reading": None, "entries": cultures, "project_label": "Culture LJ", "now": timezone.now(),
        "back_url": reverse("diagnostic:lj_reading_new")}, f"fiche_lecture_vierge_{timezone.localdate():%Y-%m-%d}.pdf")


@login_required
@permission_required("diagnostic.change_culture", raise_exception=True)
def lj_reading_new(request):
    cultures = list(in_incubator())
    date = timezone.localdate()
    if request.method == "POST":
        try:
            date = timezone.datetime.strptime(request.POST.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Date de lecture invalide.")
            return redirect("diagnostic:lj_reading_new")
        with transaction.atomic():
            reading = IncubatorReading.objects.create(
                date=date, operator=request.user, notes=request.POST.get("notes", "")[:2000],
                incubator_id=request.POST.get("incubator") or None)
            for c in cultures:
                obs = {n: request.POST.get(f"t{n}_{c.pk}", "") for n in (1, 2)}
                sd = request.POST.get(f"sd_{c.pk}", "")
                confirm = request.POST.get(f"neg_{c.pk}") == "on"
                age = (date - c.inoculated_on).days
                action, discarded = apply_reading(c, obs, sd, date, confirm, request.user)
                ReadingEntry.objects.create(reading=reading, culture=c, age_days=max(age, 0), tube1=obs[1],
                                            tube2=obs[2], sd_test=sd, action=action,
                                            discarded_tubes=", ".join(str(n) for n in discarded))
        messages.success(request, f"Lecture du {date:%d/%m/%Y} enregistrée ({len(cultures)} cultures).")
        return redirect(reading)
    for c in cultures:
        c.active_tubes = {str(t.number): t for t in c.tubes.all()}
        c.suggest_negative = (c.age_days or 0) >= Culture.NEGATIVE_AFTER_DAYS and not c.growth_on
    return render(request, "diagnostic/lj_reading_form.html", {
        "tabs": lj_tabs("reading"), "cultures": cultures, "date": date, "incubators": incubators(),
        "obs_choices": ReadingEntry.OBS[1:], "sd_choices": Culture.SD_RESULTS[1:],
        "growth_min": Culture.GROWTH_MIN_DAYS, "neg_days": Culture.NEGATIVE_AFTER_DAYS,
    })


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
           "back_url": reverse("diagnostic:lj_readings"), "now": timezone.now()}
    if request.GET.get("print") or request.GET.get("format") == "pdf":
        return render_document(request, "documents/lj_reading.html", ctx, f"lecture_etuve_{reading.date:%Y-%m-%d}.pdf")
    return render(request, "diagnostic/lj_reading.html", ctx)


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
