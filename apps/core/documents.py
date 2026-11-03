"""Documents d'un échantillon : fiche paillasse et compte rendu de résultats (HTML imprimable / PDF)."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.diagnostic.models import DST

from .analyses import first, sample_analyses
from .models import Sample
from .pdf import render_document

INCUBATION_DAYS = {"MGIT": 42, "LJ": 56}  # durée standard avant résultat négatif
XDR_DRUGS = [("inh_result", "Isoniazide (INH)"), ("fq_result", "Fluoroquinolones (FLQ)"),
             ("amk_result", "Amikacine (AMK)"), ("kan_result", "Kanamycine (KAN)"),
             ("cap_result", "Capréomycine (CAP)"), ("eto_result", "Éthionamide (ETH)")]


def person(user):
    return (user.get_full_name() or user.username) if user else ""


def base_context(sample):
    analyses = sample_analyses(sample)
    results = [r for a in analyses for r in a["results"] if hasattr(r, "is_validated")]
    project = sample.study or sample.project
    return {
        "sample": sample, "patient": sample.patient, "analyses": analyses, "today": timezone.localdate(),
        "now": timezone.now(), "project_label": str(project) if project else "—",
        "technician": next((person(r.performed_by) for r in results if r.performed_by), ""),
        "biologist": next((person(r.validated_by) for r in results if r.validated_by), ""),
        "comments": [r.comment for r in results if r.comment and "Importé automatiquement" not in r.comment],
    }


def load(pk):
    return get_object_or_404(Sample.objects.select_related("patient", "facility", "project", "study", "case"), pk=pk)


@login_required
@permission_required("core.view_sample", raise_exception=True)
def bench_sheet(request, pk):
    sample = load(pk)
    ctx = base_context(sample)
    a = ctx["analyses"]
    requested = {x["kind"] for x in a if x["requested"]}  # familles demandées (MICROSCOPY, CULTURE…)
    culture = first(a, "CULTURE")
    end, end_expected = None, False
    if culture and culture.result_date:
        end = culture.result_date
    elif culture and culture.result == "PENDING":  # date prévue de sortie si la culture reste négative
        end, end_expected = culture.inoculated_on + timedelta(days=INCUBATION_DAYS.get(culture.medium, 42)), True
    xdr = first(a, "XPERT_XDR")
    ctx.update({
        "micro": first(a, "MICROSCOPY"), "xpert": first(a, "XPERT_ULTRA"), "xdr": xdr, "culture": culture,
        "culture_end": end, "culture_end_expected": end_expected, "npoc": first(a, "NPOC"), "qft": first(a, "QFT"),
        "dsts": [r for x in a if x["kind"] == "DST" for r in x["results"]],
        "first_line_drugs": [f"{n} ({d})" for d, n in DST.DRUGS if d in DST.PANEL_DRUGS["FIRST"]],
        "requested": requested,
        "xdr_rows": [(label, getattr(xdr, f, "NA") if xdr else None) for f, label in XDR_DRUGS],
    })
    return render_document(request, "documents/bench_sheet.html", ctx, f"fiche_paillasse_{sample.code}.pdf")


@login_required
@permission_required("core.view_sample", raise_exception=True)
def result_report(request, pk):
    sample = load(pk)
    ctx = base_context(sample)
    ctx["validated"] = [(x, [r for r in x["results"] if getattr(r, "is_validated", False)])
                        for x in ctx["analyses"] if x["kind"] != "WGS"]
    ctx["pending"] = [x for x, rows in ctx["validated"] if not rows]
    ctx["validated"] = [(x, rows) for x, rows in ctx["validated"] if rows]
    return render_document(request, "documents/result_report.html", ctx, f"compte_rendu_{sample.code}.pdf")
