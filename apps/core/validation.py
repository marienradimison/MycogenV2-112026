"""Module « Validation » : tous les résultats non encore validés, filtrables, validables en lot."""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone

from .crud import REGISTRY, log


def validatable_cruds():
    return [c for c in REGISTRY.values() if getattr(c.model, "validatable", False)]


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@login_required
def validation(request):
    """Table de validation : consultation et export (core.view_validation), validation (core.validate_results)."""
    from django.core.exceptions import PermissionDenied

    from apps.research.models import Project

    can_validate = request.user.has_perm("core.validate_results")
    if not (can_validate or request.user.has_perm("core.view_validation")):
        raise PermissionDenied
    cruds = validatable_cruds()
    keys = {c.prefix: c for c in cruds}

    if request.method == "POST":
        if not can_validate:
            raise PermissionDenied
        done = 0
        for token in request.POST.getlist("items"):
            prefix, _, pk = token.partition(":")
            crud = keys.get(prefix)
            if not crud or not pk.isdigit():
                continue
            obj = crud.model.objects.filter(pk=pk, result_status="DRAFT").first()
            if obj and obj.has_result:
                comment = request.POST.get(f"comment_{token}", "")[:2000]
                obj.validate(request.user, comment)
                log(request.user, "VALIDATE", obj, {"commentaire": comment} if comment else None)
                done += 1
        if done:
            messages.success(request, f"{done} résultat(s) validé(s).")
        else:
            messages.warning(request, "Aucun résultat sélectionné.")
        return redirect(f"{request.path}?{request.POST.get('querystring', '')}")

    f = {k: request.GET.get(k, "").strip() for k in ("analyse", "du", "au", "projet", "q", "statut")}
    rows, lib = collect_rows(cruds, f, limit=None if request.GET.get("export") == "csv" else 500)
    if request.GET.get("export") == "csv":
        return export_csv(rows, f)
    used = {}   # légende : codes affichés sur la page (ex. « INH R » → INH et R)
    for r in rows:
        if r["code"]:
            used[r["code"].code] = r["code"].meaning
        for t in r["codes"]:
            used.update({p: lib[p].meaning for p in t["label"].split() if p in lib})
    statuses = STATUS_FILTERS[f["statut"]] if f["statut"] in STATUS_FILTERS else STATUS_FILTERS[""]
    tabs = [dict(t, count=t["qs"]().filter(result_status__in=statuses).count()) for t in validation_tabs(cruds)]
    tabs = [t for t in tabs if t["fixed"] or t["count"]]
    return render(request, "core/validation.html", {
        "rows": rows, "legend": sorted(used.items()), "tabs": tabs, "f": f,
        "total": sum(t["count"] for t in tabs), "statut_choices": STATUS_CHOICES,
        "projects": Project.objects.order_by("code"), "querystring": request.GET.urlencode(),
        "export_query": export_query(request.GET), "can_validate": can_validate,
    })


# Onglets du module : un onglet par test (GeneXpert Ultra / XDR, culture LJ / MGIT séparés).
# (clé, titre, préfixe du Crud, filtre)
TABS = [
    ("gx-ultra", "GeneXpert MTB/RIF Ultra", "genexpert", {"assay": "ULTRA"}),
    ("gx-xdr", "GeneXpert XDR", "genexpert", {"assay": "XDR"}),
    ("npoc", "NPOC (Pluslife)", "npoc", {}),
    ("microscopy", "Microscopie", "microscopy", {}),
    ("culture-lj", "Culture LJ", "culture", {"medium": "LJ"}),
    ("culture-mgit", "Culture MGIT", "culture", {"medium": "MGIT"}),
    ("dst", "Antibiogramme", "dst", {}),
    ("quantiferon", "QuantiFERON-TB", "quantiferon", {}),
]
STATUS_CHOICES = [("", "À valider"), ("valides", "Validés"), ("tous", "Tous")]
STATUS_FILTERS = {"": ["DRAFT"], "valides": ["VALIDATED"], "tous": ["DRAFT", "VALIDATED"]}


def validation_tabs(cruds):
    """Onglets fixes (tests de diagnostic) puis autres résultats validables (PCR, LPA…)."""
    by_prefix = {c.prefix: c for c in cruds}
    tabs = []
    for key, title, prefix, flt in TABS:
        crud = by_prefix.get(prefix)
        if crud:
            tabs.append({"key": key, "title": title, "crud": crud, "filter": flt, "fixed": True,
                         "qs": lambda crud=crud, flt=flt: with_results(crud.model.objects.filter(**flt))})
    fixed = {p for _, _, p, _ in TABS}
    for crud in cruds:
        if crud.prefix not in fixed:
            tabs.append({"key": crud.prefix, "title": str(crud.title), "crud": crud, "filter": {}, "fixed": False,
                         "qs": lambda crud=crud: with_results(crud.model.objects.all())})
    return tabs


def with_results(qs):
    """Seules les analyses dont le résultat est saisi : une culture encore en étuve (« En cours ») est exclue."""
    if any(f.name == "result" for f in qs.model._meta.fields) and qs.model._meta.model_name == "culture":
        return qs.exclude(result="PENDING")
    return qs


def collect_rows(cruds, f, limit=500):
    from .models import AnalysisCode

    catalog, lib = AnalysisCode.catalog(), AnalysisCode.result_catalog()
    d_from, d_to = parse_date(f["du"]), parse_date(f["au"])
    statuses = STATUS_FILTERS.get(f["statut"], STATUS_FILTERS[""])
    tabs = validation_tabs(cruds)
    if f["analyse"]:   # clé d'onglet, ou préfixe de Crud (tous les tests de ce type)
        tabs = [t for t in tabs if t["key"] == f["analyse"]] or [t for t in tabs if t["crud"].prefix == f["analyse"]]
    rows = []
    for tab in tabs:
        crud = tab["crud"]
        qs = tab["qs"]().filter(result_status__in=statuses).select_related(
            "sample", "sample__patient", "sample__project", "performed_by", "validated_by")
        if d_from:
            qs = qs.filter(test_date__gte=d_from)
        if d_to:
            qs = qs.filter(test_date__lte=d_to)
        if f["projet"].isdigit():
            qs = qs.filter(sample__project_id=f["projet"])
        if f["q"]:
            qs = qs.filter(Q(sample__code__icontains=f["q"]) | Q(sample__patient__last_name__icontains=f["q"])
                           | Q(sample__patient__first_name__icontains=f["q"]) | Q(sample__patient__code__icontains=f["q"]))
        for obj in qs[:limit] if limit else qs:
            rows.append({"crud": crud, "tab": tab, "obj": obj, "token": f"{crud.prefix}:{obj.pk}",
                         "summary": summarize(obj), "codes": result_codes(obj, lib),
                         "code": AnalysisCode.for_result(obj, catalog), "rendered": rendered_on(obj)})
    rows.sort(key=lambda r: (r["rendered"] or date.min, r["obj"].pk), reverse=True)  # plus récents en haut
    return rows, lib


def rendered_on(obj):
    """Date de rendu : validation si le résultat est validé, sinon date du résultat.
    Une culture encore en cours n'a pas de date de rendu."""
    if obj.validated_at:
        return timezone.localtime(obj.validated_at).date()
    if obj._meta.model_name == "culture":
        return obj.result_date
    return obj.test_date


def export_query(params):
    q = params.copy()
    q["export"] = "csv"
    return q.urlencode()


def export_csv(rows, f):
    """Export CSV (UTF-8 avec BOM, séparateur « ; ») de la table affichée : global ou par test."""
    import csv

    from django.http import HttpResponse

    name = f["analyse"] or "global"
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="validation_{name}_{timezone.localdate():%Y-%m-%d}.csv"'
    resp.write("﻿")  # BOM UTF-8 : Excel affiche correctement les accents
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Test", "Code analyse", "N° échantillon", "Identifiant externe", "Patient", "Date du test", "Date de rendu", "Résultat (codes)",
                "Résultat", "Projet", "Saisi par", "Statut", "Validé par", "Validé le", "Commentaire du validateur"])
    for r in rows:
        o = r["obj"]
        patient = o.sample.patient
        w.writerow([
            r["tab"]["title"], r["code"].code if r["code"] else "", o.sample.code,
            patient.code if patient else "", patient.full_name if patient else "",
            o.test_date.strftime("%d/%m/%Y") if o.test_date else "",
            r["rendered"].strftime("%d/%m/%Y") if r["rendered"] else "",
            " ".join(t["label"] for t in r["codes"]), r["summary"],
            o.sample.project.code if o.sample.project else "", o.performed_by or "", o.get_result_status_display(),
            o.validated_by or "", timezone.localtime(o.validated_at).strftime("%d/%m/%Y %H:%M") if o.validated_at else "",
            o.validation_comment,
        ])
    return resp

# Correspondance résultat saisi → code de la bibliothèque (catégories Résultat / Antibiotique / R-S)
GX_MTB = {"NOT_DETECTED": "GXNEG", "TRACE": "GXTRA", "VERY_LOW": "GXTBA", "LOW": "GXBAS", "MEDIUM": "GXMOY",
          "HIGH": "GXELV", "VERY_HIGH": "GXTEL"}
GX_RIF = {"NOT_DETECTED": "RIFND", "DETECTED": "RIFDE", "INDETERMINATE": "RIFIN"}
XDR_DRUGS = [("inh_result", "INH"), ("fq_result", "FLQ"), ("amk_result", "AMK"), ("kan_result", "KAN"),
             ("cap_result", "CAP"), ("eto_result", "ETH")]
DETECTION_RS = {"DETECTED": "R", "NOT_DETECTED": "S"}
GRADE_CODES = {"SCANTY": "RARE", "1-19": "RARE", "1+": "100", "2+": "200", "3+": "300"}
NEGATIVE_CODES = {"GXNEG", "RIFND"}


def result_codes(obj, lib):
    """Résultat mis en forme pour la liste de validation : [{label, title, cls}], vide si non représentable.
    Classes : pos (bordure rouge), neg (bordure verte), alert (rouge sans bordure, précédé de « ! »),
    pending (bordure bleue), muted (non fait / non applicable).
    Les codes de la bibliothèque ne sont utilisés que s'ils sont présents et actifs."""
    name = obj._meta.model_name
    out = []

    def chip(label, cls, title=""):
        out.append({"label": label, "title": title or label, "cls": cls})

    def add(code, extra="", cls=None):
        c = lib.get(code)
        if not c:
            return False
        cls = cls or ("neg" if code in NEGATIVE_CODES else "pos" if c.category == "RESULT" else "")
        chip(code, cls, c.meaning + extra)
        return True

    def add_drug(drug, value):
        """Antibiotique + résultat (ex. « INH R »)."""
        value = DETECTION_RS.get(value, "I" if value == "INDETERMINATE" else value)
        if not value:
            return
        d, v = lib.get(drug), lib.get(value)
        title = f"{d.meaning if d else drug} : {v.meaning if v else value}"
        cls = {"R": "pos", "S": "neg", "I": "alert"}.get(value, "muted")
        chip(f"{drug} {value}", cls, title)

    if name == "genexperttest":
        if not add(GX_MTB.get(obj.mtb_result, "")):
            return []
        if obj.assay == "ULTRA":
            add(GX_RIF.get(obj.rif_result, ""), cls="alert" if obj.rif_result == "INDETERMINATE" else None)
        elif obj.mtb_positive:
            for field, drug in XDR_DRUGS:
                if getattr(obj, field) != "NA":
                    add_drug(drug, getattr(obj, field))
    elif name == "microscopy":
        if obj.grade == "NEG":
            chip("Négatif", "neg", obj.get_grade_display())
        elif obj.grade == "NA":
            chip("Non interprétable", "alert")
        elif not (obj.method == "FM" and add(GRADE_CODES.get(obj.grade, ""),
                                             f" ({obj.afb_count} BAAR)" if obj.afb_count else "")):
            chip(obj.get_grade_display(), "pos")
    elif name == "culture":
        if obj.result == "PENDING":
            chip("En cours", "pending", "Culture en cours")
        elif obj.result == "CONTAMINATED":
            chip("Contaminée", "alert")
        elif obj.result == "NEGATIVE":
            chip("Négative", "neg")
        elif not (obj.medium == "LJ" and add(GRADE_CODES.get(obj.lj_grade, ""),
                                             f" ({obj.colony_count} colonies)" if obj.colony_count else "")):
            chip("Positive", "pos")
    elif name == "quantiferon":
        chip(*{"POS": ("Positif", "pos"), "NEG": ("Négatif", "neg"), "IND": ("Indéterminé", "alert")}
             .get(obj.interpretation, ("—", "muted")))
    elif name == "npoctest":
        if obj.mtb_result == "DETECTED":
            chip("Positif", "pos", obj.get_mtb_result_display())
        elif obj.mtb_result == "NOT_DETECTED":
            chip("Négatif", "neg", obj.get_mtb_result_display())
        else:
            chip("Indéterminé", "alert", obj.get_mtb_result_display())
    elif name == "dst":
        for drug, _, value, _ in obj.drug_results:
            add_drug(drug, value)
    return out

def summarize(obj):
    """Résumé lisible du résultat pour la liste de validation."""
    name = obj._meta.model_name
    if name == "genexperttest":
        s = f"MTB : {obj.get_mtb_result_display()}"
        if obj.assay == "ULTRA" and obj.rif_result != "NA":
            s += f" · RIF : {obj.get_rif_result_display()}"
        if obj.assay == "XDR":
            res = [lbl for f, lbl in (("inh_result", "INH"), ("fq_result", "FLQ"), ("amk_result", "AMK"),
                                      ("kan_result", "KAN"), ("cap_result", "CAP"), ("eto_result", "ETH"))
                   if getattr(obj, f) == "DETECTED"]
            s += f" · R : {', '.join(res)}" if res else ""
        return s
    if name == "microscopy":
        return f"{obj.get_method_display()} : {obj.get_grade_display()}"
    if name == "culture":
        return f"{obj.medium} : {obj.get_result_display()}"
    if name == "dst":
        return f"{obj.get_panel_display()} : {obj.results_display}"
    if name == "npoctest":
        return obj.get_mtb_result_display()
    if name == "quantiferon":
        return f"QFT : {obj.get_interpretation_display()}"
    if name == "pcrassay":
        return f"{obj.run.get_assay_display()} · score {obj.score if obj.score is not None else '—'} · {obj.get_outcome_display()}"
    if name == "lpatest":
        return f"{obj.get_kit_display()} · RIF {obj.get_rif_display()} · INH {obj.get_inh_katg_display()}"
    return str(obj)
