"""Module « Enregistrer » : enregistrement (et modification) d'un échantillon en 2 étapes.

Étape 1 « Général » : fiche patient complète + informations échantillon.
Étape 2 « Examens » : projet / étude / cas, analyses demandées, conformité.
"""
import re
from datetime import datetime, time

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .crud import log
from .forms import BootstrapFormMixin
from .models import Facility, Patient, Sample
from .status import refresh_status

DATE = {"type": "date"}
ISO = "%Y-%m-%d"  # format attendu par <input type="date"> (sinon la date affichée en jj/mm/aaaa est effacée)


def analysis_choices(sample=None):
    """Codes proposés à l'enregistrement (+ ceux déjà demandés sur l'échantillon modifié)."""
    from .models import AnalysisCode
    codes = AnalysisCode.objects.filter(active=True, requestable=True, category="ANALYSIS")
    out = [(c.code, c.meaning) for c in codes]
    for code in (sample.requested_analyses if sample else []) or []:
        if code not in dict(out):
            out.append((code, code))
    return out

PATIENT_FIELDS = ["full_name", "birth_date", "sex", "patient_id", "national_id", "tb_register_number", "phone",
                  "address", "district", "region", "hiv_status", "tb_history", "research_consent", "patient_notes"]
SAMPLE_FIELDS = ["code", "host", "sample_type", "type_detail", "aspect", "collected_on", "received_at", "facility",
                 "requester", "requester_contact"]


class RegistrationForm(BootstrapFormMixin, forms.Form):
    # --- Étape 1 : fiche patient
    full_name = forms.CharField(label="Nom & Prénom", max_length=250,
                                widget=forms.TextInput(attrs={"placeholder": "RAKOTO Jean", "autocomplete": "off"}))
    birth_date = forms.DateField(label="Date de naissance", widget=forms.DateInput(attrs=DATE, format=ISO))
    sex = forms.ChoiceField(label="Sexe", required=False, choices=[("", "—")] + Patient.SEX[:2])
    patient_id = forms.CharField(label="Identifiant externe", max_length=30, required=False,
                                 help_text="Un identifiant peut être partagé par plusieurs patients : en cas de "
                                           "correspondance, choisir le patient ou « nouveau patient ». "
                                           "Vide : identifiant attribué automatiquement.")
    # patient choisi : n° interne d'un patient existant, « new » pour un nouveau patient, vide = non précisé
    patient_pk = forms.CharField(required=False, widget=forms.HiddenInput)
    national_id = forms.CharField(label="N° CIN / identifiant", max_length=50, required=False)
    tb_register_number = forms.CharField(label="N° registre TB", max_length=50, required=False)
    phone = forms.CharField(label="Téléphone", max_length=30, required=False)
    address = forms.CharField(label="Adresse", max_length=255, required=False)
    district = forms.CharField(label="District", max_length=100, required=False)
    region = forms.CharField(label="Région", max_length=100, required=False)
    hiv_status = forms.ChoiceField(label="Statut VIH", choices=Patient.HIV, initial="INC")
    tb_history = forms.ChoiceField(label="Antécédent TB", choices=Patient.TB_HISTORY, initial="NEW")
    research_consent = forms.BooleanField(label="Consentement pour la recherche", required=False)
    patient_notes = forms.CharField(label="Remarques patient", required=False,
                                    widget=forms.Textarea(attrs={"rows": 2}))
    # --- Étape 1 : échantillon
    code = forms.CharField(label="N° Échantillon", max_length=30,
                           widget=forms.TextInput(attrs={"pattern": r"\d{2}-\d{4,}", "placeholder": "26-0001"}))
    host = forms.CharField(label="Hôte", max_length=60, required=False,
                           widget=forms.TextInput(attrs={"list": "host-options", "autocomplete": "off"}))
    sample_type = forms.ChoiceField(label="Type de prélèvement", choices=[("", "—")] + Sample.TYPES)
    type_detail = forms.CharField(label="Précision", max_length=120, required=False,
                                  widget=forms.TextInput(attrs={"placeholder": "Ex. 2 mL"}))
    aspect = forms.CharField(label="Aspect", max_length=60, required=False,
                             widget=forms.TextInput(attrs={"list": "aspect-options", "autocomplete": "off",
                                                           "placeholder": "Ex. Muco-purulent"}))
    collected_on = forms.DateField(label="Date de prélèvement", required=False, widget=forms.DateInput(attrs=DATE, format=ISO))
    received_at = forms.DateTimeField(label="Date de réception",
                                      widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    facility = forms.ModelChoiceField(label="Provenance / CDT", required=False,
                                      queryset=Facility.objects.filter(active=True).order_by("code"))
    requester = forms.CharField(label="Prescripteur", max_length=150, required=False)
    requester_contact = forms.CharField(label="Contact prescripteur", max_length=120, required=False,
                                        widget=forms.TextInput(attrs={"placeholder": "Téléphone ou e-mail"}))
    # --- Étape 2 : examens
    project = forms.ModelChoiceField(label="Projet", required=False, queryset=None)
    study = forms.ModelChoiceField(label="Étude", required=False, queryset=None)
    case = forms.ModelChoiceField(label="Cas", required=False, queryset=None)
    case_text = forms.CharField(label="Cas", max_length=120, required=False)
    analyses = forms.MultipleChoiceField(label="Analyses", required=False, choices=[],
                                         widget=forms.CheckboxSelectMultiple)
    conform = forms.BooleanField(label="Échantillon conforme", required=False, initial=True)
    non_conformity = forms.CharField(label="Motif de non-conformité", max_length=255, required=False)
    notes = forms.CharField(label="Remarques échantillon", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    STEP1 = PATIENT_FIELDS + SAMPLE_FIELDS

    def __init__(self, *args, instance=None, **kwargs):
        from apps.research.models import Project, ProjectCase, Study

        self.instance = instance
        super().__init__(*args, **kwargs)
        projects = Project.objects.filter(status="ACTIVE")
        if instance and instance.project_id:  # garder un projet clôturé déjà attribué
            projects = Project.objects.filter(pk=instance.project_id) | projects
        self.fields["project"].queryset = projects.distinct()
        self.fields["study"].queryset = Study.objects.select_related("project").prefetch_related("cases")
        self.fields["case"].queryset = ProjectCase.objects.select_related("project")
        self.fields["analyses"].choices = analysis_choices(instance)

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not re.fullmatch(Sample.CODE_RE, code):
            raise forms.ValidationError("Format attendu : année-numéro, ex. 26-0001.")
        qs = Sample.objects.filter(code=code)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Le n° {code} existe déjà. Prochain n° libre : {Sample.next_code(2000 + int(code[:2]))}.")
        return code

    def clean_birth_date(self):
        d = self.cleaned_data["birth_date"]
        if d > timezone.localdate():
            raise forms.ValidationError("La date de naissance ne peut pas être dans le futur.")
        return d

    def clean(self):
        data = super().clean()
        project = data.get("project")
        for name in ("study", "case"):
            obj = data.get(name)
            if obj and obj.project_id != getattr(project, "pk", None):
                self.add_error(name, "N'appartient pas au projet choisi.")
        self.check_case(data)
        collected, received = data.get("collected_on"), data.get("received_at")
        if collected and received and collected > timezone.localtime(received).date():
            self.add_error("collected_on", "Le prélèvement ne peut pas être postérieur à la réception.")
        if not data.get("conform") and not data.get("non_conformity"):
            self.add_error("non_conformity", "Précisez le motif de non-conformité.")
        return data

    def check_case(self, data):
        """Cas selon la configuration de l'étude : liste spécifique, cas du projet, texte libre ou aucun."""
        study, case = data.get("study"), data.get("case")
        mode = study.case_mode if study else "PROJECT"
        if mode in ("TEXT", "NONE"):
            data["case"] = None
            if mode == "NONE":
                data["case_text"] = ""
            return
        data["case_text"] = ""
        if study and case and "case" not in self.errors:
            kept = self.instance and self.instance.case_id == case.pk  # cas déjà attribué, devenu inactif
            if not (kept or study.allowed_cases().filter(pk=case.pk).exists()):
                self.add_error("case", f"Ce cas n'est pas autorisé pour l'étude {study.code}.")

    def step_of_errors(self):
        return 1 if any(f in self.errors for f in self.STEP1) else 2


def initial_from(sample):
    p = sample.patient
    data = {
        "code": sample.code, "sample_type": sample.sample_type, "type_detail": sample.type_detail,
        "collected_on": timezone.localtime(sample.collected_at).date() if sample.collected_at else None,
        "received_at": timezone.localtime(sample.received_at).replace(second=0, microsecond=0),
        "facility": sample.facility_id, "requester": sample.requester,
        "requester_contact": sample.requester_contact, "aspect": sample.aspect, "host": sample.host, "project": sample.project_id,
        "study": sample.study_id, "case": sample.case_id, "case_text": sample.case_text, "analyses": sample.requested_analyses,
        "conform": sample.conform, "non_conformity": sample.non_conformity,
        "notes": sample.notes,
    }
    if p:
        data.update(patient_initial(p))
    return data


def patient_initial(p):
    return {"patient_pk": str(p.pk), "full_name": p.full_name, "birth_date": p.birth_date, "sex": p.sex if p.sex != "I" else "",
            "patient_id": p.code, "national_id": p.national_id, "tb_register_number": p.tb_register_number,
            "phone": p.phone, "address": p.address, "district": p.district, "region": p.region,
            "hiv_status": p.hiv_status, "tb_history": p.tb_history, "research_consent": p.research_consent,
            "patient_notes": p.notes}


def render_wizard(request, form, sample=None):
    for name in form.errors:
        if name in form.fields:
            form.fields[name].widget.attrs["class"] = form.fields[name].widget.attrs.get("class", "") + " is-invalid"
    return render(request, "core/register.html", {
        "form": form, "sample": sample, "step": form.step_of_errors() if form.is_bound and form.errors else 1,
        "patient_fields": [form[f] for f in PATIENT_FIELDS],
        "sample_fields": [form[f] for f in SAMPLE_FIELDS], "aspects": Sample.ASPECTS, "hosts": Sample.HOSTS,
    })


@login_required
@permission_required("core.add_sample", raise_exception=True)
def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            sample = save_registration(form.cleaned_data, request.user)
            messages.success(request, f"Échantillon {sample.code} enregistré pour {sample.patient.full_name}.")
            return redirect("core:register" if "another" in request.POST else sample.get_absolute_url())
    else:
        initial = {"code": Sample.next_code(), "received_at": timezone.localtime().replace(second=0, microsecond=0),
                   "conform": True, "hiv_status": "INC", "tb_history": "NEW", "host": "Humain"}
        for key in ("facility", "project"):  # liens « Ajouter » depuis une fiche CDT / projet
            if request.GET.get(key, "").isdigit():
                initial[key] = int(request.GET[key])
        patient = Patient.objects.filter(pk=request.GET.get("patient") or 0).first()
        if patient:
            initial.update(patient_initial(patient))
        form = RegistrationForm(initial=initial)
    return render_wizard(request, form)


@login_required
@permission_required("core.change_sample", raise_exception=True)
def register_edit(request, pk):
    sample = get_object_or_404(Sample.objects.select_related("patient"), pk=pk)
    if request.method == "POST":
        form = RegistrationForm(request.POST, instance=sample)
        if form.is_valid():
            save_registration(form.cleaned_data, request.user, sample=sample)
            messages.success(request, f"Échantillon {sample.code} modifié.")
            return redirect(sample)
    else:
        form = RegistrationForm(initial=initial_from(sample), instance=sample)
    return render_wizard(request, form, sample)


def apply_patient(patient, d, user):
    patient.last_name, patient.first_name = Patient.split_name(d["full_name"])
    patient.birth_date = d["birth_date"]
    patient.sex = d["sex"] or "I"
    for f in ("national_id", "tb_register_number", "phone", "address", "district", "region",
              "hiv_status", "tb_history", "research_consent"):
        setattr(patient, f, d[f])
    patient.notes = d["patient_notes"]
    patient.updated_by = user


@transaction.atomic
def save_registration(d, user, sample=None):
    pid = d["patient_id"].strip()
    current = sample.patient if sample else None
    choice = (d.get("patient_pk") or "").strip()
    # Un identifiant externe peut être partagé par plusieurs patients : le patient existant n'est repris
    # que s'il a été choisi explicitement (sinon, nouveau patient ; en modification, patient actuel).
    patient = Patient.objects.filter(pk=choice).first() if choice.isdigit() else None
    if patient is None and choice != "new" and current:
        patient = current
    created = patient is None
    if created:
        patient = Patient(code=pid, created_by=user)
    elif pid or not patient.code:
        patient.code = pid
    apply_patient(patient, d, user)
    patient.save()
    log(user, "CREATE" if created else "UPDATE", patient)

    collected = d["collected_on"]
    values = {
        "code": d["code"], "patient": patient, "facility": d["facility"], "requester": d["requester"],
        "requester_contact": d["requester_contact"], "aspect": d["aspect"], "host": d["host"],
        "sample_type": d["sample_type"], "type_detail": d["type_detail"],
        "collected_at": timezone.make_aware(datetime.combine(collected, time(0, 0))) if collected else None,
        "received_at": d["received_at"], "project": d["project"], "study": d["study"], "case": d["case"],
        "case_text": d["case_text"],
        "requested_analyses": d["analyses"], "conform": d["conform"],
        "non_conformity": "" if d["conform"] else d["non_conformity"], "notes": d["notes"],
    }
    if sample is None:
        sample = Sample.objects.create(**values, reason="RES" if d["project"] else "DIAG", created_by=user,
                                       updated_by=user, status="RECEIVED" if d["conform"] else "REJECTED")
        log(user, "CREATE", sample)
    else:
        changes = {k: str(v) for k, v in values.items() if getattr(sample, k) != v}
        for k, v in values.items():
            setattr(sample, k, v)
        sample.updated_by = user
        sample.save()
        log(user, "UPDATE", sample, changes)
    refresh_status(sample)   # statut automatique (analyses demandées / résultats / validation)
    return sample


@login_required
@permission_required("core.view_patient", raise_exception=True)
def patient_lookup(request):
    """Patients ayant l'identifiant externe saisi (?id=) ; ou fiche complète d'un patient choisi (?pk=)."""
    if request.GET.get("pk"):
        p = get_object_or_404(Patient, pk=request.GET["pk"])
    else:
        pid = request.GET.get("id", "").strip()
        matches = Patient.objects.filter(code__iexact=pid).order_by("last_name", "first_name") if pid else []
        return JsonResponse({"found": bool(matches), "matches": [{
            "pk": m.pk, "full_name": m.full_name, "birth_date": m.birth_date.strftime("%d/%m/%Y") if m.birth_date else "",
            "age": m.age, "sex": m.get_sex_display() if m.sex != "I" else "", "samples": m.samples.count(),
        } for m in matches[:20]]})
    data = patient_initial(p)
    data["birth_date"] = p.birth_date.isoformat() if p.birth_date else ""
    last = p.samples.order_by("-received_at").first()
    return JsonResponse({"found": True, **data, "samples": p.samples.count(),
                         "facility": last.facility_id if last and last.facility_id else ""})
