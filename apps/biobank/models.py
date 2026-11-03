import re
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import CodedModel, LimsModel


class StorageUnit(LimsModel):
    url_base = "biobank:unit"

    TYPES = [("-80", "Congélateur −80 °C"), ("-20", "Congélateur −20 °C"), ("4", "Réfrigérateur +4 °C"),
             ("LN2", "Azote liquide"), ("RT", "Température ambiante"), ("OTHER", "Autre")]
    name = models.CharField("nom", max_length=100, unique=True)
    type = models.CharField("type", max_length=5, choices=TYPES)
    room = models.ForeignKey("core.Room", verbose_name="salle", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="storage_units")
    location = models.CharField("précision d'emplacement", max_length=100, blank=True)
    serial_number = models.CharField("n° de série", max_length=60, blank=True)
    active = models.BooleanField("en service", default=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "congélateur / unité de stockage"
        verbose_name_plural = "congélateurs / unités de stockage"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"


class StorageBox(LimsModel):
    url_base = "biobank:box"

    unit = models.ForeignKey(StorageUnit, verbose_name="unité de stockage", on_delete=models.PROTECT,
                             related_name="boxes")
    name = models.CharField("nom de la boîte", max_length=100)
    shelf = models.CharField("étagère", max_length=30, blank=True)
    rack = models.CharField("rack", max_length=30, blank=True)
    rows = models.PositiveSmallIntegerField("lignes", default=9)
    cols = models.PositiveSmallIntegerField("colonnes", default=9)
    content = models.CharField("contenu principal", max_length=100, blank=True)

    class Meta:
        verbose_name = "boîte"
        verbose_name_plural = "boîtes"
        ordering = ["unit", "shelf", "rack", "name"]
        unique_together = [("unit", "name")]

    def __str__(self):
        loc = " / ".join(x for x in (self.unit.name, self.shelf, self.rack) if x)
        return f"{self.name} [{loc}]"

    @property
    def capacity(self):
        return self.rows * self.cols

    def row_labels(self):
        return string.ascii_uppercase[: self.rows]

    def occupied(self):
        return self.items.exclude(status__in=BiobankItem.GONE).count()

    def grid(self):
        items = {i.position.upper(): i for i in self.items.exclude(status__in=BiobankItem.GONE)}
        return [
            (r, [(f"{r}{c}", items.get(f"{r}{c}")) for c in range(1, self.cols + 1)])
            for r in self.row_labels()
        ]


class BiobankItem(CodedModel):
    url_base = "biobank:item"
    code_prefix = "BB"

    TYPES = [
        ("SPECIMEN", "Prélèvement primaire"),
        ("SEDIMENT", "Culot / sédiment décontaminé"),
        ("ISOLATE", "Souche (isolat)"),
        ("DNA", "ADN"),
        ("RNA", "ARN"),
        ("PLASMA", "Plasma"),
        ("SERUM", "Sérum"),
        ("BLOOD", "Sang total"),
        ("PAXGENE", "Tube PAXgene"),
        ("PBMC", "PBMC"),
        ("DBS", "Carte DBS"),
        ("QFT_SN", "Surnageant QuantiFERON"),
        ("OTHER", "Autre"),
    ]
    UNITS = [("uL", "µL"), ("mL", "mL"), ("ng", "ng"), ("card", "carte(s)"), ("spot", "spot(s)"),
             ("tube", "tube(s)"), ("vial", "cryotube(s)")]
    STATUS = [("AVAILABLE", "Disponible"), ("RESERVED", "Réservé"), ("IN_USE", "Sorti / en utilisation"),
              ("SHIPPED", "Transféré"), ("EXHAUSTED", "Épuisé"), ("DESTROYED", "Détruit")]
    GONE = ("SHIPPED", "EXHAUSTED", "DESTROYED")

    item_type = models.CharField("type", max_length=10, choices=TYPES)
    sample = models.ForeignKey("core.Sample", verbose_name="échantillon source", on_delete=models.PROTECT,
                               null=True, blank=True, related_name="biobank_items")
    parent = models.ForeignKey("self", verbose_name="dérivé de", on_delete=models.PROTECT,
                               null=True, blank=True, related_name="children",
                               help_text="Ex. ADN extrait d'une souche")
    project = models.ForeignKey("research.Project", verbose_name="projet", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="biobank_items")
    label = models.CharField("étiquette / ID externe", max_length=80, blank=True)
    quantity = models.DecimalField("quantité", max_digits=10, decimal_places=2, null=True, blank=True)
    unit = models.CharField("unité", max_length=5, choices=UNITS, default="uL")
    concentration = models.DecimalField("concentration (ng/µL)", max_digits=10, decimal_places=2,
                                        null=True, blank=True)
    purity_260_280 = models.DecimalField("pureté A260/280", max_digits=4, decimal_places=2, null=True, blank=True)
    box = models.ForeignKey(StorageBox, verbose_name="boîte", on_delete=models.PROTECT,
                            null=True, blank=True, related_name="items")
    position = models.CharField("position", max_length=5, blank=True, help_text="Ex. A1, C7")
    stored_on = models.DateField("date de stockage", default=timezone.localdate)
    status = models.CharField("statut", max_length=10, choices=STATUS, default="AVAILABLE")
    freeze_thaw = models.PositiveSmallIntegerField("cycles congélation/décongélation", default=0)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "élément de biobanque"
        verbose_name_plural = "biobanque"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} — {self.get_item_type_display()}"

    @property
    def location(self):
        if not self.box:
            return ""
        return f"{self.box} · {self.position}" if self.position else str(self.box)

    def clean(self):
        self.position = self.position.strip().upper()
        if self.box and self.position:
            m = re.fullmatch(r"([A-Z])(\d{1,2})", self.position)
            if not m or m.group(1) not in self.box.row_labels() or not 1 <= int(m.group(2)) <= self.box.cols:
                raise ValidationError({"position": f"Position invalide pour une boîte {self.box.rows}×{self.box.cols}."})
            clash = (BiobankItem.objects.filter(box=self.box, position=self.position)
                     .exclude(status__in=self.GONE).exclude(pk=self.pk))
            if clash.exists():
                raise ValidationError({"position": f"Position déjà occupée par {clash.first().code}."})


class Movement(LimsModel):
    url_base = "biobank:movement"

    TYPES = [("OUT", "Sortie"), ("RETURN", "Retour en stock"), ("THAW", "Décongélation"),
             ("SHIP", "Transfert / envoi"), ("CONSUME", "Épuisement"), ("DESTROY", "Destruction"),
             ("MOVE", "Changement d'emplacement")]
    NEW_STATUS = {"OUT": "IN_USE", "RETURN": "AVAILABLE", "SHIP": "SHIPPED",
                  "CONSUME": "EXHAUSTED", "DESTROY": "DESTROYED"}

    item = models.ForeignKey(BiobankItem, verbose_name="élément", on_delete=models.CASCADE, related_name="movements")
    type = models.CharField("type de mouvement", max_length=8, choices=TYPES)
    date = models.DateTimeField("date", default=timezone.now)
    quantity = models.DecimalField("quantité prélevée", max_digits=10, decimal_places=2, null=True, blank=True)
    destination = models.CharField("destinataire / destination", max_length=200, blank=True)
    reason = models.CharField("motif", max_length=255, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="opérateur", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "mouvement de biobanque"
        verbose_name_plural = "mouvements de biobanque"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.get_type_display()} — {self.item.code}"

    def save(self, *args, **kwargs):
        creating = self._state.adding
        super().save(*args, **kwargs)
        if creating:
            item = self.item
            if self.type in self.NEW_STATUS:
                item.status = self.NEW_STATUS[self.type]
            if self.type == "THAW":
                item.freeze_thaw += 1
            if self.quantity and item.quantity is not None:
                item.quantity = max(item.quantity - self.quantity, 0)
            item.save()
