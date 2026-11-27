"""Aperçu d'un résultat d'analyse (fiche détaillée commune à tous les résultats validables).

Bandeau (échantillon, date d'analyse, méthode, résultat), informations générales, patient, validation
biologique (avec la signature du validateur), métadonnées et frise de traçabilité.
"""
from django.utils import timezone

from .signature import caption, signature_html

METHOD_FIELDS = ("method", "medium", "assay", "kit", "panel")
RESULT_FIELDS = ("grade", "mtb_result", "interpretation", "result", "outcome")   # résultat principal (bandeau)
HIDDEN = {"id", "sample", "test_date", "created_at", "updated_at", "created_by", "updated_by", "performed_by",
          "result_status", "validated_by", "validated_at", "validation_comment", "comment"}
EMPTY = "Non renseigné"


def person(user):
    return (user.get_full_name() or user.username) if user else ""


def method_of(obj):
    """(nom du champ, libellé affiché) de la méthode / du test, ou (None, nom du type de résultat)."""
    for name in METHOD_FIELDS:
        try:
            obj._meta.get_field(name)
        except Exception:
            continue
        display = getattr(obj, f"get_{name}_display", None)
        value = display() if display else getattr(obj, name)
        if obj._meta.model_name == "dst" and name == "method":
            value = f"{value} — {obj.get_panel_display()}"
        return name, value
    if obj._meta.model_name == "quantiferon":
        return None, "QuantiFERON-TB Gold Plus (ELISA)"
    return None, obj._meta.verbose_name.capitalize()


def result_chips(obj):
    from .models import AnalysisCode
    from .validation import result_codes, summarize

    chips = result_codes(obj, AnalysisCode.result_catalog())
    if obj._meta.model_name == "microscopy" and chips:       # libellé complet, ex. « Négatif (0 BAAR) »
        chips = [dict(chips[0], label=obj.get_grade_display())]
    if obj._meta.model_name == "quantiferon":
        cls = {"POS": "pos", "NEG": "neg", "IND": "alert"}.get(obj.interpretation, "muted")
        chips = [{"label": obj.get_interpretation_display() or "—", "cls": cls, "title": summarize(obj)}]
    return chips or [{"label": summarize(obj), "cls": "muted", "title": summarize(obj)}]


def result_context(obj, extra_details=()):
    from .templatetags.lims import render_value
    from .validation import rendered_on

    method_field, method_label = method_of(obj)
    main_result = next((n for n in RESULT_FIELDS if hasattr(obj, f"get_{n}_display")), None)
    sample = obj.sample
    patient = sample.patient if sample else None

    general = [("Créé par", person(obj.created_by) or EMPTY), ("Modifié par", person(obj.updated_by) or EMPTY),
               ("Réalisé par", person(obj.performed_by) or EMPTY)]
    for f in obj._meta.get_fields():
        if not f.concrete or f.auto_created or f.name in HIDDEN or f.name in (method_field, main_result):
            continue
        if obj._meta.model_name == "dst" and f.name in ("panel", "results"):
            continue
        value = render_value(obj, f.name)
        general.append((f.verbose_name[:1].upper() + f.verbose_name[1:], EMPTY if value == "—" else value))
    if obj._meta.model_name == "dst":
        for code, name, value, label in obj.drug_results:
            general.append((f"{name} ({code})", f"{value} — {label}" if value else EMPTY))
    general += [(label, value if value not in ("", None, "—") else EMPTY) for label, value in extra_details]
    general.append(("Commentaire", obj.comment or EMPTY))

    patient_rows = []
    if patient:
        patient_rows = [
            ("Identifiant externe", patient.code or EMPTY), ("Nom", patient.last_name or EMPTY),
            ("Prénom(s)", patient.first_name or EMPTY),
            ("Sexe", patient.get_sex_display() if patient.sex else EMPTY),
            ("Âge", f"{patient.age} ans" if getattr(patient, "age", None) not in (None, "") else EMPTY),
        ]
    patient_rows.append(("Structure / CDT", str(sample.facility) if sample and sample.facility_id else EMPTY))

    rendered = rendered_on(obj)
    created = timezone.localtime(obj.created_at) if obj.created_at else None
    timeline = [
        ("Enregistré", created.strftime("%d/%m/%Y %H:%M") if created else "", bool(created)),
        ("Analyse réalisée", obj.test_date.strftime("%d/%m/%Y") if obj.test_date else "", bool(obj.test_date)),
        ("Rendu résultat", rendered.strftime("%d/%m/%Y") if rendered else "", bool(rendered)),
        ("Validé", timezone.localtime(obj.validated_at).strftime("%d/%m/%Y %H:%M") if obj.validated_at else "",
         bool(obj.validated_at)),
    ]
    return {
        "band": {"sample": sample, "method": method_label, "chips": result_chips(obj)},
        "general": general, "patient_rows": patient_rows, "patient": patient, "timeline": timeline,
        "validator": person(obj.validated_by), "validator_caption": caption(obj.validated_by) if obj.validated_by else "",
        "validator_signature": signature_html(obj.validated_by) if obj.validated_at else "",
    }
