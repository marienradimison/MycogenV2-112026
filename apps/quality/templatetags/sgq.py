from django import template

register = template.Library()


@register.filter
def pct(value):
    """12.3 → « 12,3 % » ; None → « — »."""
    return "—" if value is None else f"{value:.1f}".replace(".", ",") + " %"


@register.filter
def num(value):
    """Nombre au format français (espace fine pour les milliers, virgule décimale) ; None → « — »."""
    if value is None:
        return "—"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}".replace(".", ",")
    return f"{int(value):,}".replace(",", " ")
