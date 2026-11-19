import datetime
from decimal import Decimal

from django import template
from django.db import models
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.html import format_html

from apps.core.crud import resolve

register = template.Library()

# Couleur des badges selon la valeur brute d'un champ à choix
BADGES = {
    "success": {"VALIDATED", "NOT_DETECTED", "NEGATIVE", "NEG", "S", "AVAILABLE", "DONE", "COMPLETED",
                "ACTIVE", "SENSITIVE", "REVIEWED", "IMPORTED", "OK"},
    "danger": {"DETECTED", "POSITIVE", "POS", "R", "TRACE", "VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "RR",
               "MDR", "PREXDR", "XDR", "HR", "REJECTED", "FAILED", "UNMATCHED", "DOWN", "QUARANTINE", "1+", "2+", "3+", "SCANTY", "DESTROYED"},
    "warning": {"DRAFT", "PENDING", "PENDING_VALIDATION", "INDETERMINATE", "IND", "IN_PROGRESS", "RUNNING", "QUEUED", "CONTAMINATED",
                "I", "CONT", "RESERVED", "IN_USE", "INVALID", "ERROR", "NO_RESULT", "NEW", "MAINT"},
    "info": {"RECEIVED", "PLANNED", "SHIPPED", "INFO"},
}
BADGE_FIELDS = {"result_status", "status", "mtb_result", "rif_result", "inh_result", "fq_result", "amk_result",
                "kan_result", "cap_result", "eto_result", "grade", "result", "interpretation", "outcome",
                "rif", "inh_katg", "inh_inha", "fq", "sli", "drug_profile"}


def badge_class(value):
    for cls, values in BADGES.items():
        if value in values:
            return cls
    return "secondary"


def render_value(obj, name, link=True):
    leaf = name.split("__")[-1]
    holder = resolve(obj, "__".join(name.split("__")[:-1])) if "__" in name else obj
    if holder is None:
        return "—"
    raw = getattr(holder, leaf, None)
    try:
        field = holder._meta.get_field(leaf)
    except Exception:
        field = None
    if field is not None and field.choices and not field.is_relation:
        if raw in (None, "", "NA"):  # « Non applicable » → tiret, plus compact dans les tableaux
            return "—"
        label = getattr(holder, f"get_{leaf}_display")()
        if leaf in BADGE_FIELDS and raw != "NA":
            return format_html('<span class="badge text-bg-{}">{}</span>', badge_class(raw), label)
        return label
    if field is not None and field.many_to_many:
        return ", ".join(str(o) for o in raw.all()) or "—"
    if callable(raw) and not isinstance(raw, models.Model):
        raw = raw()
    if raw is None or raw == "":
        return "—"
    if isinstance(raw, bool):
        return format_html('<i class="bi {}"></i>', "bi-check-circle-fill text-success" if raw else "bi-x-circle text-muted")
    if isinstance(raw, models.Model):
        if link and hasattr(raw, "get_absolute_url") and getattr(raw, "url_base", None):
            return format_html('<a href="{}">{}</a>', raw.get_absolute_url(), raw)
        return str(raw)
    if isinstance(raw, datetime.datetime):
        return formats.date_format(timezone.localtime(raw), "d/m/Y H:i")
    if isinstance(raw, datetime.date):
        return formats.date_format(raw, "d/m/Y")
    if isinstance(raw, Decimal):
        return formats.number_format(raw.normalize() if raw == raw.to_integral() else raw)
    if hasattr(raw, "url") and hasattr(raw, "name"):  # FileField
        return format_html('<a href="{}" target="_blank"><i class="bi bi-file-earmark-arrow-down"></i> {}</a>',
                           raw.url, raw.name.split("/")[-1])
    return str(raw)


@register.simple_tag
def cell(obj, name):
    return render_value(obj, name)


@register.simple_tag
def avatar(user, size=34):
    """Photo de profil ou initiales d'un utilisateur."""
    try:
        profile = user.profile
    except Exception:
        profile = None
    style = f"width:{size}px;height:{size}px;font-size:{size * 0.36:.0f}px"
    if profile and profile.photo:
        return format_html('<img class="avatar" style="{}" src="{}" alt="">', style, profile.photo.url)
    initials = ((user.first_name[:1] + user.last_name[:1]) or user.username[:2]).upper()
    return format_html('<span class="avatar" style="{}">{}</span>', style, initials)


@register.simple_tag
def cell_link(obj, name):
    """Cellule servant de lien vers `obj` (sans lien imbriqué)."""
    return format_html('<a class="fw-semibold" href="{}">{}</a>', obj.get_absolute_url(),
                       render_value(obj, name, link=False))


@register.simple_tag
def crud_url(crud, action, pk=None):
    return reverse(crud.url(action), args=[pk] if pk is not None else [])


@register.filter
def has_perm(user, perm):
    return user.has_perm(perm)


@register.simple_tag
def crud_perm(user, crud, action):
    return user.has_perm(crud.perm(action))


MTB_LABELS = {"NOT_DETECTED": "Non détecté", "TRACE": "Détecté (Trace)", "VERY_LOW": "Détecté (Très faible)",
              "LOW": "Détecté (Faible)", "MEDIUM": "Détecté (Moyen)", "HIGH": "Détecté (Élevé)", "VERY_HIGH": "Détecté (Très élevé)",
              "DETECTED": "Détecté", "INVALID": "Invalide", "ERROR": "Erreur", "NO_RESULT": "Pas de résultat"}
RES_LABELS = {"DETECTED": "Détectée (Résistant)", "NOT_DETECTED": "Non détectée (Sensible)",
              "INDETERMINATE": "Indéterminée", "NA": "Non applicable"}


@register.filter
def split(value, sep=None):
    return (value or "").split(sep)


@register.filter
def mtb_res(value):
    return MTB_LABELS.get(value, value or "—")


@register.filter
def res_res(value):
    return RES_LABELS.get(value, value or "—")


@register.filter
def rs(value):
    """GeneXpert XDR : R (résistance détectée), S (non détectée), I (indéterminé)."""
    return {"DETECTED": "R", "NOT_DETECTED": "S", "INDETERMINATE": "I"}.get(value, "—")


@register.filter
def positive(value):
    """Classe CSS d'un résultat pour les comptes rendus."""
    if value in ("NOT_DETECTED", "NEG", "NEGATIVE", "S"):
        return "res-neg"
    if value in ("TRACE", "VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "DETECTED", "POS", "POSITIVE", "R",
                 "SCANTY", "1+", "2+", "3+"):
        return "res-pos"
    return ""


@register.filter
def ago(value):
    """« à l'instant », « il y a 5 minutes », puis la date au-delà d'une semaine."""
    from django.utils.timesince import timesince
    delta = timezone.now() - value
    if delta.total_seconds() < 60:
        return "à l'instant"
    if delta.days >= 7:
        return formats.date_format(timezone.localtime(value), "d/m/Y H:i")
    return "il y a " + timesince(value).split(",")[0]


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if hasattr(mapping, "get") else None


@register.filter
def is_long(value):
    return isinstance(value, str) and len(value) > 80


@register.simple_tag
def signature(user, css_class="signature-img"):
    """Image de la signature d'un utilisateur (vide s'il n'en a pas) : {% signature r.validated_by %}."""
    from apps.core.signature import signature_html
    return signature_html(user, css_class)


@register.filter
def signature_caption(user):
    from apps.core.signature import caption
    return caption(user)
