"""Correspondance entre les analyses demandées (codes de la bibliothèque) et les résultats saisis."""
from django.urls import reverse


def families():
    """famille -> (modèle, champ de méthode, préfixe d'URL, valeurs initiales fixes)."""
    from apps.diagnostic.models import DST, Culture, GeneXpertTest, Microscopy, NPOCTest, Quantiferon
    from apps.research.models import SequencingLibrary

    return {
        "XPERT_ULTRA": (GeneXpertTest, None, "diagnostic:genexpert", {"assay": "ULTRA"}),
        "XPERT_XDR": (GeneXpertTest, None, "diagnostic:genexpert", {"assay": "XDR"}),
        "MICROSCOPY": (Microscopy, "method", "diagnostic:microscopy", {}),
        "CULTURE": (Culture, "medium", "diagnostic:culture", {}),
        "DST": (DST, "method", "diagnostic:dst", {}),
        "NPOC": (NPOCTest, None, "diagnostic:npoc", {}),
        "QFT": (Quantiferon, None, "diagnostic:quantiferon", {}),
        "WGS": (SequencingLibrary, None, "research:library", {}),
    }


def is_cancelled(result):
    return getattr(result, "result_status", None) == "CANCELLED"


def sample_analyses(sample, user=None):
    """Analyses (codes demandés ou ayant un résultat) avec leurs résultats, dans l'ordre de la bibliothèque."""
    from apps.core.models import AnalysisCode

    catalog = AnalysisCode.catalog()
    fams = families()
    requested = list(sample.requested_analyses or [])
    # résultats existants, regroupés par code
    by_code = {}
    loaded = {}
    for kind, (model, method_field, url, fixed) in fams.items():
        key = (model, tuple(fixed.items()))
        if key not in loaded:
            qs = model.objects.filter(sample=sample, **fixed)
            loaded[key] = list(qs.select_related(*[f for f in ("validated_by", "performed_by")
                                                   if hasattr(model, f)]))
        for obj in loaded[key]:
            c = AnalysisCode.for_result(obj, catalog)
            if c and c.kind == kind:
                by_code.setdefault(c.code, []).append(obj)

    out = []
    codes = [c for c in catalog if c in requested or c in by_code]
    codes += [c for c in requested if c not in catalog]  # code supprimé de la bibliothèque
    for code in codes:
        entry = catalog.get(code)
        results = by_code.get(code, [])
        active = [r for r in results if not is_cancelled(r)]   # un résultat annulé ne compte pas
        validatable = bool(results) and hasattr(results[0], "is_validated")
        if not active:
            state = "PENDING"
        elif not validatable:
            state = "DONE"
        else:
            state = "VALIDATED" if all(r.is_validated for r in active) else "DRAFT"
        add_url = None
        if entry and entry.kind in fams:
            model, method_field, url, fixed = fams[entry.kind]
            params = {"sample": sample.pk, **fixed}
            if method_field and entry.method:
                params[method_field] = entry.method
            if user is None or user.has_perm(f"{model._meta.app_label}.add_{model._meta.model_name}"):
                query = "&".join(f"{k}={v}" for k, v in params.items())
                add_url = f"{reverse(url + '_create')}?{query}&next={sample.get_absolute_url()}"
        out.append({
            "code": code, "label": entry.meaning if entry else code, "kind": entry.kind if entry else "OTHER",
            "method": entry.method if entry else "", "requested": code in requested, "results": results,
            "state": state, "validatable": validatable or not results, "add_url": add_url,
        })
    return out


def first(analyses, kind):
    """Premier résultat d'une famille (ex. MICROSCOPY, quelle que soit la méthode)."""
    for a in analyses:
        if a["kind"] == kind and a["results"]:
            return a["results"][0]
    return None
