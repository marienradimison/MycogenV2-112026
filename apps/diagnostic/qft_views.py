"""QuantiFERON-TB Gold Plus : plaques ELISA, saisie des DO et générateur de fiches de résultats."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from apps.core.crud import Crud, log
from apps.core.forms import LimsModelForm, lims_formfield
from apps.core.models import Sample
from apps.core.pdf import render_document

from . import qft
from .models import QFTRun, Quantiferon

RESULT_FIELDS = ["test_date", "performed_by", "comment"]
OD_FIELDS = ["od_nil", "od_tb1", "od_tb2", "od_mitogen"]
IU_FIELDS = ["nil", "tb1", "tb2", "mitogen"]


class QuantiferonForm(LimsModelForm):
    """Deux modes : DO brutes + plaque (UI/mL calculés), ou UI/mL saisis directement."""

    class Meta:
        model = Quantiferon
        fields = ["sample", "run", *OD_FIELDS, "kit_lot", *IU_FIELDS, *RESULT_FIELDS]
        formfield_callback = lims_formfield

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in IU_FIELDS:
            self.fields[name].required = False
            self.fields[name].help_text = "Calculé depuis les DO si une plaque est choisie"
        for name in OD_FIELDS:
            self.fields[name].help_text = "Valeur lue (ex. 0,248) ; texte (OVER, > 4) = 4,000"

    def clean(self):
        data = super().clean()
        run, ods = data.get("run"), [data.get(n) for n in OD_FIELDS]
        if any(ods):
            if not run:
                self.add_error("run", "Choisissez la plaque ELISA pour calculer les UI/mL depuis les DO.")
            elif not all(ods):
                for n in OD_FIELDS:
                    if not data.get(n):
                        self.add_error(n, "Saisissez les 4 DO (Nul, TB1, TB2, Mitogène).")
            else:
                probe = Quantiferon(run=run, **{n: data[n] for n in OD_FIELDS})
                if not probe.compute_from_ods():
                    raise forms.ValidationError("Courbe standard de la plaque incalculable : vérifiez les DO des standards.")
                for n in IU_FIELDS:
                    data[n] = getattr(probe, n)
        elif any(data.get(n) is None for n in IU_FIELDS):
            raise forms.ValidationError("Saisissez les DO brutes avec la plaque, ou les 4 valeurs en UI/mL.")
        return data


def qft_run_context(run, request):
    curve = run.curve
    results = list(run.results.select_related("sample", "sample__patient").order_by("sample__code"))
    return {
        "curve": curve, "results": [(q, qft.sheet_rows(q)) for q in results],
        "can_add_results": request.user.has_perm("diagnostic.add_quantiferon"),
        "slope": f"{curve.slope:.4f}".replace(".", ",") if curve.slope is not None else "—",
        "intercept": f"{curve.intercept:.4f}".replace(".", ",") if curve.intercept is not None else "—",
        "r": f"{curve.r:.2f}".replace(".", ",") if curve.r is not None else "—",
        "blank_rows": range(8),
    }


CRUDS = [
    Crud(
        QFTRun, "qftrun",
        fields=["run_id", "run_date", "operator", "kit_lot", "s1_od1", "s1_od2", "s2_od1", "s2_od2", "s3_od1",
                "s3_od2", "s4_od1", "s4_od2", "notes"],
        list_display=["run_id", "run_date", "operator", "kit_lot", ("n_results", "Échantillons")],
        search_fields=["run_id", "kit_lot", "results__sample__code"],
        list_filter=["operator"],
        icon="bi-grid-3x3-gap",
        detail_template="diagnostic/qft_run.html",
        extra_context=qft_run_context,
        header_links=[("Résultats QuantiFERON", "diagnostic:quantiferon_list", "bi-activity")],
    ),
    Crud(
        Quantiferon, "quantiferon",
        fields=QuantiferonForm.Meta.fields,
        form_class=QuantiferonForm,
        list_display=["sample", "sample__patient", "test_date", "run", "nil", "tb1", "tb2", "mitogen",
                      "interpretation", "result_status"],
        search_fields=["sample__code", "sample__patient__last_name", "sample__patient__code", "kit_lot",
                       "run__run_id"],
        list_filter=["interpretation", "result_status", "run"],
        icon="bi-activity",
        extra_context=lambda obj, request: {"doc_links": [
            ("Fiche de résultats QFT", reverse("diagnostic:quantiferon_sheet", args=[obj.pk]), "bi-file-earmark-medical")]},
        header_links=[("Plaques ELISA et fiches de résultats", "diagnostic:qftrun_list", "bi-grid-3x3-gap")],
    ),
]


@login_required
@permission_required("diagnostic.add_quantiferon", raise_exception=True)
def run_add_results(request, pk):
    """Saisie groupée des DO d'une plaque : une ligne par échantillon (N° échantillon + 4 DO)."""
    run = get_object_or_404(QFTRun, pk=pk)
    if request.method != "POST":
        return redirect(run.get_absolute_url())
    codes = request.POST.getlist("sample")
    columns = {n: request.POST.getlist(n) for n in OD_FIELDS}
    created, updated, errors = 0, 0, []
    with transaction.atomic():
        for i, code in enumerate(codes):
            code = code.strip()
            ods = {n: (columns[n][i] if i < len(columns[n]) else "").strip() for n in OD_FIELDS}
            if not code and not any(ods.values()):
                continue
            sample = Sample.objects.filter(code=code).first()
            if not sample:
                errors.append(f"{code or '(vide)'} : échantillon introuvable")
                continue
            if not all(ods.values()):
                errors.append(f"{code} : les 4 DO sont obligatoires")
                continue
            q = Quantiferon.objects.filter(sample=sample, run=run).first()
            if q and q.is_validated:
                errors.append(f"{code} : résultat déjà validé, non modifié")
                continue
            is_new = q is None
            q = q or Quantiferon(sample=sample, run=run, test_date=run.run_date,
                                 performed_by=run.operator or request.user, created_by=request.user)
            for n, v in ods.items():
                setattr(q, n, v[:10])
            if not q.compute_from_ods():
                errors.append(f"{code} : courbe standard incalculable")
                continue
            q.updated_by = request.user
            q.save()
            log(request.user, "CREATE" if is_new else "UPDATE", q)
            created += is_new
            updated += not is_new
    if created or updated:
        messages.success(request, f"{created} résultat(s) ajouté(s), {updated} mis à jour.")
    for e in errors:
        messages.error(request, e)
    return redirect(run.get_absolute_url())


def sheet_context(q):
    raw = []
    for name in OD_FIELDS:
        od, _ = qft.parse_od(getattr(q, name))
        raw.append(f"{od:.3f}".replace(".", ",") if od is not None else "—")
    return {"q": q, "row": qft.sheet_rows(q), "curve": q.run.curve if q.run_id else None, "sample": q.sample,
            "patient": q.sample.patient, "raw": raw}


@login_required
@permission_required("diagnostic.view_quantiferon", raise_exception=True)
def result_sheet(request, pk):
    """Fiche « Résultats QuantiFERON®-TB Gold Plus » d'un échantillon (HTML imprimable ou PDF)."""
    q = get_object_or_404(Quantiferon.objects.select_related("sample", "sample__patient", "run", "run__operator",
                                                             "performed_by", "validated_by"), pk=pk)
    ctx = {"sheets": [sheet_context(q)], "sample": q.sample, "back_url": q.get_absolute_url(),
           "now": timezone.now()}
    return render_document(request, "documents/qft_sheet.html", ctx, f"QFT_{q.sample.code}.pdf")


@login_required
@permission_required("diagnostic.view_quantiferon", raise_exception=True)
def run_sheets(request, pk):
    """Toutes les fiches de résultats d'une plaque, une page par échantillon."""
    run = get_object_or_404(QFTRun, pk=pk)
    results = run.results.select_related("sample", "sample__patient", "performed_by", "validated_by") \
        .order_by("sample__code")
    if request.GET.get("valides") == "1":
        results = results.filter(result_status="VALIDATED")
    ctx = {"sheets": [sheet_context(q) for q in results], "back_url": run.get_absolute_url(), "now": timezone.now(),
           "sample": None}
    return render_document(request, "documents/qft_sheet.html", ctx, f"QFT_{run.run_id}.pdf")

