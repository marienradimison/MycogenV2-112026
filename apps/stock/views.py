from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.crud import Crud, log
from apps.core.forms import LimsModelForm, lims_formfield

from .models import EXPIRY_WARNING_DAYS, Article, Lot, Movement, stock_alerts


def stock_tabs(active):
    items = [("home", "Tableau de bord", "bi-speedometer2", "stock:home"),
             ("article", "Articles", "bi-box2", "stock:article_list"),
             ("lot", "Lots", "bi-upc-scan", "stock:lot_list"),
             ("movement", "Mouvements", "bi-arrow-left-right", "stock:movement_list")]
    return [(k, label, icon, reverse(url), k == active) for k, label, icon, url in items]


class MovementForm(LimsModelForm):
    class Meta:
        model = Movement
        fields = ["lot", "kind", "quantity", "date", "destination", "operator", "comment"]
        formfield_callback = lims_formfield

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # lots disponibles, les plus proches de la péremption en premier (FEFO)
        lots = Lot.objects.select_related("article").prefetch_related("movements").order_by("expiry_date", "received_on")
        current = self.instance.lot_id
        self.fields["lot"].queryset = lots
        self.fields["lot"].label_from_instance = lambda l: (
            f"{l.article.name} · lot {l.lot_number} · {l.remaining:g} {l.unit_label}"
            + (f" · exp. {l.expiry_date:%d/%m/%Y}" if l.expiry_date else ""))
        self.fields["lot"].choices = [("", "—")] + [
            (l.pk, self.fields["lot"].label_from_instance(l)) for l in lots if l.remaining > 0 or l.pk == current]


CRUDS = [
    Crud(
        Article, "article",
        fields=["name", "reference", "category", "unit", "supplier", "min_stock", "storage", "room", "location",
                "active", "notes"],
        list_display=["name", "reference", "category", ("quantity", "Stock disponible"), "unit", "min_stock",
                      "storage", "room"],
        search_fields=["name", "reference", "supplier"],
        list_filter=["category", "storage", "active"],
        icon="bi-box2",
        list_tabs=lambda: stock_tabs("article"),
    ),
    Crud(
        Lot, "lot",
        fields=["article", "lot_number", "expiry_date", "received_on", "quantity_received", "supplier",
                "delivery_ref", "opened_on", "notes"],
        list_display=["article", "lot_number", "received_on", "expiry_date", "quantity_received",
                      ("remaining", "Restant")],
        search_fields=["lot_number", "article__name", "article__reference", "delivery_ref"],
        list_filter=["article"],
        ordering=["expiry_date", "received_on"],
        icon="bi-upc-scan",
        list_tabs=lambda: stock_tabs("lot"),
    ),
    Crud(
        Movement, "movement",
        fields=MovementForm.Meta.fields,
        form_class=MovementForm,
        list_display=["date", "lot", "kind", "quantity", "destination", "operator"],
        search_fields=["lot__lot_number", "lot__article__name", "destination", "comment"],
        list_filter=["kind"],
        icon="bi-arrow-left-right",
        list_tabs=lambda: stock_tabs("movement"),
    ),
]


@login_required
@permission_required("stock.view_article", raise_exception=True)
def home(request):
    alerts = stock_alerts()
    form = MovementForm(initial={"operator": request.user.pk, "kind": "OUT", "date": timezone.localdate()})
    if request.method == "POST":
        if not request.user.has_perm("stock.add_movement"):
            messages.error(request, "Vous n'avez pas le droit d'enregistrer une sortie de stock.")
            return redirect("stock:home")
        form = MovementForm(request.POST)
        if form.is_valid():
            m = form.save(commit=False)
            m.created_by = m.updated_by = request.user
            m.operator = m.operator or request.user
            m.save()
            log(request.user, "CREATE", m)
            messages.success(request, f"{m.get_kind_display()} enregistrée : {m.quantity:g} {m.lot.unit_label} — {m.lot.article.name}.")
            return redirect("stock:home")
    today = timezone.localdate()
    month = Movement.objects.filter(date__gte=today.replace(day=1))
    return render(request, "stock/home.html", {
        "tabs": stock_tabs("home"), "alerts": alerts, "form": form, "warn_days": EXPIRY_WARNING_DAYS,
        "stats": {"articles": len(alerts["articles"]), "low": len(alerts["low"]), "expired": len(alerts["expired"]),
                  "soon": len(alerts["soon"]), "month_out": month.filter(kind="OUT").count()},
        "recent": Movement.objects.select_related("lot__article", "operator")[:10],
        "can_move": request.user.has_perm("stock.add_movement"),
    })
