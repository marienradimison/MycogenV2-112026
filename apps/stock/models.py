"""Stock du laboratoire : articles (réactifs, kits, cartouches, consommables), lots et mouvements.

Le stock d'un lot = quantité reçue ± mouvements ; le stock d'un article = somme de ses lots.
Alertes : stock sous le seuil, lots périmés ou proches de la péremption.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import LimsModel

EXPIRY_WARNING_DAYS = 60


class Article(LimsModel):
    url_base = "stock:article"

    CATEGORIES = [
        ("CARTRIDGE", "Cartouches / tests automates"), ("KIT", "Kits"), ("REAGENT", "Réactifs"),
        ("MEDIA", "Milieux de culture"), ("STAIN", "Colorants"), ("CONSUMABLE", "Consommables"),
        ("PPE", "Équipements de protection (EPI)"), ("DISINFECT", "Désinfectants"), ("OTHER", "Autre"),
    ]
    UNITS = [("unit", "unité(s)"), ("box", "boîte(s)"), ("kit", "kit(s)"), ("cartridge", "cartouche(s)"),
             ("tube", "tube(s)"), ("bottle", "flacon(s)"), ("pack", "paquet(s)"), ("mL", "mL"), ("L", "L"),
             ("g", "g"), ("test", "test(s)")]
    STORAGE = [("RT", "Température ambiante"), ("4", "+2 / +8 °C"), ("-20", "−20 °C"), ("-80", "−80 °C")]

    name = models.CharField("désignation", max_length=150)
    reference = models.CharField("référence fournisseur", max_length=80, blank=True)
    category = models.CharField("catégorie", max_length=10, choices=CATEGORIES, default="REAGENT")
    unit = models.CharField("unité", max_length=10, choices=UNITS, default="unit")
    supplier = models.CharField("fournisseur", max_length=150, blank=True)
    min_stock = models.DecimalField("seuil d'alerte", max_digits=10, decimal_places=2, default=0,
                                    help_text="Alerte quand le stock disponible descend à ce niveau")
    storage = models.CharField("conservation", max_length=4, choices=STORAGE, default="RT")
    room = models.ForeignKey("core.Room", verbose_name="salle de stockage", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="stock_articles")
    location = models.CharField("emplacement précis", max_length=120, blank=True,
                                help_text="Ex. armoire 2, réfrigérateur réactifs")
    active = models.BooleanField("actif", default=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "article"
        verbose_name_plural = "articles"
        ordering = ["name"]

    def __str__(self):
        return self.name + (f" ({self.reference})" if self.reference else "")

    @property
    def quantity(self):
        """Stock disponible (lots non périmés)."""
        today = timezone.localdate()
        return sum((lot.remaining for lot in self.lots.all() if not (lot.expiry_date and lot.expiry_date < today)),
                   Decimal(0))

    @property
    def level(self):
        """'out' | 'low' | 'ok'"""
        q = self.quantity
        if q <= 0:
            return "out"
        if q <= self.min_stock:
            return "low"
        return "ok"


class Lot(LimsModel):
    url_base = "stock:lot"

    article = models.ForeignKey(Article, verbose_name="article", on_delete=models.PROTECT, related_name="lots")
    lot_number = models.CharField("n° de lot", max_length=60)
    expiry_date = models.DateField("date de péremption", null=True, blank=True)
    received_on = models.DateField("reçu le", default=timezone.localdate)
    quantity_received = models.DecimalField("quantité reçue", max_digits=10, decimal_places=2)
    supplier = models.CharField("fournisseur", max_length=150, blank=True)
    delivery_ref = models.CharField("n° bon de livraison / commande", max_length=80, blank=True)
    opened_on = models.DateField("ouvert le", null=True, blank=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "lot"
        verbose_name_plural = "lots"
        ordering = ["expiry_date", "received_on"]

    def __str__(self):
        exp = f" — exp. {self.expiry_date:%d/%m/%Y}" if self.expiry_date else ""
        return f"{self.article.name} · lot {self.lot_number}{exp}"

    @property
    def remaining(self):
        moved = sum((m.signed for m in self.movements.all()), Decimal(0))
        return (self.quantity_received or 0) + moved

    @property
    def expiry_state(self):
        if not self.expiry_date:
            return None
        today = timezone.localdate()
        if self.expiry_date < today:
            return "expired"
        if self.expiry_date <= today + timedelta(days=EXPIRY_WARNING_DAYS):
            return "soon"
        return "ok"

    @property
    def unit_label(self):
        return self.article.get_unit_display()


class Movement(LimsModel):
    url_base = "stock:movement"

    KINDS = [("OUT", "Sortie / consommation"), ("RETURN", "Retour en stock"), ("ADJUST", "Ajustement d'inventaire"),
             ("LOSS", "Perte / péremption / casse")]
    lot = models.ForeignKey(Lot, verbose_name="lot", on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField("type", max_length=6, choices=KINDS, default="OUT")
    quantity = models.DecimalField("quantité", max_digits=10, decimal_places=2,
                                   help_text="Ajustement : quantité positive (ajout) ou négative (retrait)")
    date = models.DateField("date", default=timezone.localdate)
    destination = models.CharField("destination / usage", max_length=150, blank=True,
                                   help_text="Ex. paillasse GeneXpert, salle 7, série du 12/10")
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="effectué par", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="+")
    comment = models.CharField("commentaire", max_length=255, blank=True)

    class Meta:
        verbose_name = "mouvement de stock"
        verbose_name_plural = "mouvements de stock"
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.quantity} · {self.lot}"

    @property
    def signed(self):
        q = self.quantity or 0
        if self.kind in ("OUT", "LOSS"):
            return -abs(q)
        if self.kind == "RETURN":
            return abs(q)
        return q

    def clean(self):
        if self.quantity is None or not self.lot_id:
            return
        if self.kind != "ADJUST" and self.quantity <= 0:
            raise ValidationError({"quantity": "La quantité doit être positive."})
        if self.kind in ("OUT", "LOSS"):
            available = self.lot.remaining - (self.signed_before() if self.pk else 0)
            if abs(self.quantity) > available:
                raise ValidationError({"quantity": f"Stock insuffisant sur ce lot ({available} disponible)."})

    def signed_before(self):
        old = Movement.objects.filter(pk=self.pk).first()
        return old.signed if old else 0


def stock_alerts():
    """Articles sous le seuil / épuisés, lots périmés et proches de la péremption."""
    articles = list(Article.objects.filter(active=True).prefetch_related("lots__movements"))
    low = [a for a in articles if a.level in ("low", "out")]
    lots = [lot for a in articles for lot in a.lots.all() if lot.remaining > 0]
    expired = [lot for lot in lots if lot.expiry_state == "expired"]
    soon = [lot for lot in lots if lot.expiry_state == "soon"]
    return {"articles": articles, "low": low, "expired": expired, "soon": soon}


def month_movements():
    start = timezone.localdate().replace(day=1)
    return Movement.objects.filter(date__gte=start).aggregate(n=models.Count("id"))["n"], \
        Movement.objects.filter(date__gte=start, kind="OUT").aggregate(q=Sum("quantity"))["q"]
