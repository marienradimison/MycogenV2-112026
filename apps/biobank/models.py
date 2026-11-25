import re
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.core.models import CodedModel, LimsModel

# Types d'aliquot : (code, libellé, abréviation des boîtes, libellé de l'étiquette des boîtes)
ITEM_TYPES = [
    ("SPECIMEN", "Prélèvement primaire", "PRL", "Prélèvements"),
    ("SEDIMENT", "Culot / sédiment décontaminé", "CUL", "Culots"),
    ("ISOLATE", "Souche (isolat)", "SCH", "Souches"),
    ("DNA", "ADN", "ADN", "ADN"),
    ("RNA", "ARN", "ARN", "ARN"),
    ("PLASMA", "Plasma", "PLA", "Plasma"),
    ("SERUM", "Sérum", "SER", "Sérum"),
    ("BLOOD", "Sang total", "SNG", "Sang total"),
    ("PAXGENE", "Tube PAXgene", "PAX", "PAXgene"),
    ("PBMC", "PBMC", "PBM", "PBMC"),
    ("DBS", "Carte DBS", "DBS", "Cartes DBS"),
    ("QFT_SN", "Surnageant QuantiFERON", "QFT", "Surnageants QFT"),
    ("OTHER", "Autre", "AUT", "Divers"),
]
TYPE_CHOICES = [(code, label) for code, label, _, _ in ITEM_TYPES]
TYPE_ABBR = {code: abbr for code, _, abbr, _ in ITEM_TYPES}
TYPE_BOX_LABEL = {code: box_label for code, _, _, box_label in ITEM_TYPES}
ABBR_TYPE = {abbr: code for code, abbr in TYPE_ABBR.items()}

# Solutions de conservation proposées (saisie libre possible)
PRESERVATIONS = [
    "Glycérol 15 %", "Glycérol 20 %", "Middlebrook 7H9 + glycérol", "Lait écrémé (skim milk)",
    "Tampon TE", "Eau ultrapure", "Éthanol 70 %", "RNAlater", "PAXgene", "Trizol", "EDTA", "Aucune (sec)",
]


def level_code(prefix, value):
    """Étagère / rack : « 3 » → « E03 », « r1 » → « R01 » ; un libellé libre est conservé (en majuscules)."""
    v = (value or "").strip().upper()
    m = re.fullmatch(rf"{prefix}?\s*0*(\d{{1,3}})", v)
    return f"{prefix}{int(m.group(1)):02d}" if m else v


def position_code(position):
    """Position affichée dans les chemins : B7 → B07."""
    m = re.fullmatch(r"([A-Z])(\d{1,2})", (position or "").upper())
    return f"{m.group(1)}{int(m.group(2)):02d}" if m else (position or "")


class StorageUnit(LimsModel):
    url_base = "biobank:unit"

    TYPES = [("-80", "Congélateur −80 °C"), ("-20", "Congélateur −20 °C"), ("4", "Réfrigérateur +4 °C"),
             ("LN2", "Azote liquide"), ("RT", "Température ambiante"), ("OTHER", "Autre")]
    name = models.CharField("nom", max_length=100, unique=True, help_text="Ex. MYCO-2209")
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

    def capacity(self):
        return sum(b.capacity for b in self.boxes.all())

    def occupied(self):
        return BiobankItem.objects.filter(box__unit=self).exclude(status__in=BiobankItem.GONE).count()


class StorageBox(LimsModel):
    """Boîte de stockage. Nom par défaut : <abréviation du type>-<année>-<n°>, ex. SCH-2026-01.

    La numérotation est propre à chaque type d'aliquot et repart à 01 chaque année.
    """

    url_base = "biobank:box"
    NAME_RE = re.compile(r"^([A-Z]{2,4})-(\d{4})-(\d{2,})$")

    unit = models.ForeignKey(StorageUnit, verbose_name="congélateur", on_delete=models.PROTECT,
                             related_name="boxes")
    item_type = models.CharField("type d'aliquot", max_length=10, choices=TYPE_CHOICES, blank=True,
                                 help_text="Détermine l'abréviation et la numérotation de la boîte")
    year = models.PositiveSmallIntegerField("année", null=True, blank=True,
                                            help_text="Année de création (par défaut : année en cours)")
    number = models.PositiveSmallIntegerField("n° de la boîte", null=True, blank=True,
                                              help_text="Laisser vide : numéro suivant attribué automatiquement")
    name = models.CharField("nom de la boîte", max_length=100, blank=True,
                            help_text="Laisser vide : nom automatique (ex. SCH-2026-01)")
    shelf = models.CharField("étagère", max_length=30, blank=True, help_text="Ex. 3 ou E03")
    rack = models.CharField("rack", max_length=30, blank=True, help_text="Ex. 1 ou R01")
    rows = models.PositiveSmallIntegerField("lignes", default=9)
    cols = models.PositiveSmallIntegerField("colonnes", default=9)
    content = models.CharField("contenu principal", max_length=100, blank=True,
                               help_text="Libellé de l'étiquette (par défaut : le type d'aliquot)")

    class Meta:
        verbose_name = "boîte"
        verbose_name_plural = "boîtes"
        ordering = ["unit", "shelf", "rack", "name"]
        unique_together = [("unit", "name")]

    def __str__(self):
        return self.name or "Nouvelle boîte"

    # -- numérotation ---------------------------------------------------------
    @property
    def abbr(self):
        return TYPE_ABBR.get(self.item_type, "")

    @classmethod
    def next_number(cls, item_type, year, exclude_pk=None):
        qs = cls.objects.filter(item_type=item_type, year=year)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        numbers = [n for n in qs.values_list("number", flat=True) if n]
        return (max(numbers) + 1) if numbers else 1

    @classmethod
    def build_name(cls, item_type, year, number):
        return f"{TYPE_ABBR[item_type]}-{year}-{number:02d}"

    def clean(self):
        self.shelf, self.rack = level_code("E", self.shelf), level_code("R", self.rack)
        self.name = (self.name or "").strip().upper()
        if not self.name and not self.item_type:
            raise ValidationError({"item_type": "Choisissez le type d'aliquot (ou saisissez un nom de boîte)."})
        year = self.year or timezone.localdate().year
        if self.item_type and self.number:
            clash = StorageBox.objects.filter(item_type=self.item_type, year=year, number=self.number).exclude(pk=self.pk)
            if clash.exists():
                raise ValidationError({"number": f"Le n° {self.number:02d} est déjà pris ({clash.first().name})."})
        name = self.name or (self.build_name(self.item_type, year, self.number) if self.number else "")
        if name and StorageBox.objects.filter(name=name).exclude(pk=self.pk).exists():
            raise ValidationError({"name": f"Une boîte « {name} » existe déjà."})

    def save(self, *args, **kwargs):
        self.shelf, self.rack = level_code("E", self.shelf), level_code("R", self.rack)
        self.name = (self.name or "").strip().upper()
        if not self.year:
            self.year = timezone.localdate().year
        m = self.NAME_RE.match(self.name)
        if m and m.group(1) in ABBR_TYPE:  # nom saisi au format normalisé : type, année et n° en sont déduits
            self.item_type = self.item_type or ABBR_TYPE[m.group(1)]
            if ABBR_TYPE[m.group(1)] == self.item_type:
                self.year, self.number = int(m.group(2)), int(m.group(3))
        if self.name or not self.item_type:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            if not self.number:
                self.number = self._locked_next_number()
            self.name = self.build_name(self.item_type, self.year, self.number)
            return super().save(*args, **kwargs)

    def _locked_next_number(self):
        from django.db import connection
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                            [f"{self._meta.db_table}:{self.item_type}:{self.year}"])
        list(StorageBox.objects.select_for_update().filter(item_type=self.item_type, year=self.year)
             .values_list("pk", flat=True))
        return self.next_number(self.item_type, self.year, exclude_pk=self.pk)

    # -- localisation et étiquette -------------------------------------------
    @property
    def path_parts(self):
        return [x for x in (self.unit.name, self.shelf, self.rack, self.name) if x]

    @property
    def path(self):
        """Chemin de la boîte : MYCO-2209/E03/R01/SCH-2026-01."""
        return "/".join(self.path_parts)

    @property
    def label(self):
        return (self.content or TYPE_BOX_LABEL.get(self.item_type, "")).upper()

    @property
    def capacity(self):
        return self.rows * self.cols

    @property
    def format_display(self):
        return f"{self.rows}x{self.cols} : {self.capacity} positions"

    def row_labels(self):
        return string.ascii_uppercase[: self.rows]

    def occupied(self):
        return self.items.exclude(status__in=BiobankItem.GONE).count()

    def free(self):
        return self.capacity - self.occupied()

    def occupancy_pct(self):
        return round(100 * self.occupied() / self.capacity) if self.capacity else 0

    def grid(self):
        items = {i.position.upper(): i for i in self.items.exclude(status__in=BiobankItem.GONE)}
        return [
            (r, [(f"{r}{c}", items.get(f"{r}{c}")) for c in range(1, self.cols + 1)])
            for r in self.row_labels()
        ]


class BiobankItem(CodedModel):
    """Aliquot / souche. Son code est le n° de l'échantillon source (26-4244, puis 26-4244-2, 26-4244-3…)."""

    url_base = "biobank:item"
    code_prefix = "BB"

    TYPES = TYPE_CHOICES
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
    preservation = models.CharField("solution de conservation", max_length=80, blank=True,
                                    help_text="Ex. glycérol 15 %, tampon TE, RNAlater…")
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
        verbose_name = "aliquot / souche"
        verbose_name_plural = "aliquots & souches"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} — {self.get_item_type_display()}"

    @property
    def path(self):
        """Localisation : MYCO-2209/E03/R01/SCH-2026-01/B07."""
        if not self.box_id:
            return ""
        parts = self.box.path_parts + ([position_code(self.position)] if self.position else [])
        return "/".join(parts)

    @property
    def location(self):
        return self.path

    @staticmethod
    def normalize_position(position):
        m = re.fullmatch(r"([A-Z])0*(\d{1,2})", (position or "").strip().upper())
        return f"{m.group(1)}{int(m.group(2))}" if m else (position or "").strip().upper()

    def check_position(self, box, position, exclude_pk=None):
        """Erreur (texte) si la position n'existe pas dans la boîte ou est déjà occupée, sinon None."""
        m = re.fullmatch(r"([A-Z])(\d{1,2})", position)
        if not m or m.group(1) not in box.row_labels() or not 1 <= int(m.group(2)) <= box.cols:
            return f"Position invalide pour une boîte {box.rows}×{box.cols}."
        clash = (BiobankItem.objects.filter(box=box, position=position)
                 .exclude(status__in=self.GONE).exclude(pk=exclude_pk))
        if clash.exists():
            return f"Position déjà occupée par {clash.first().code}."
        return None

    def fill_from_sources(self):
        """Échantillon, projet et étiquette repris de l'aliquot parent puis de l'échantillon source."""
        if not self.sample_id and self.parent_id and self.parent.sample_id:
            self.sample_id = self.parent.sample_id
        if self.sample_id:
            if not self.project_id:
                self.project_id = self.sample.project_id
            if not self.label and self.sample.patient_id:
                self.label = self.sample.patient.code  # identifiant externe saisi à l'enregistrement
        elif self.parent_id and not self.project_id:
            self.project_id = self.parent.project_id

    def clean(self):
        self.position = self.normalize_position(self.position)
        if self.box and self.position:
            error = self.check_position(self.box, self.position, exclude_pk=self.pk)
            if error:
                raise ValidationError({"position": error})

    def next_sample_code(self):
        base = self.sample.code
        codes = list(BiobankItem.objects.select_for_update()
                     .filter(models.Q(code=base) | models.Q(code__startswith=f"{base}-"))
                     .values_list("code", flat=True))
        if base not in codes:
            return base
        numbers = [int(c[len(base) + 1:]) for c in codes if c[len(base) + 1:].isdigit()]
        return f"{base}-{max(numbers + [1]) + 1}"

    def save(self, *args, **kwargs):
        self.position = self.normalize_position(self.position)
        self.fill_from_sources()
        creating = self._state.adding
        before = None
        if not creating and not getattr(self, "_skip_trace", False):
            before = BiobankItem.objects.filter(pk=self.pk).select_related("box__unit").first()
        with transaction.atomic():
            if not self.code and self.sample_id:
                self.code = self.next_sample_code()
            super().save(*args, **kwargs)
            if getattr(self, "_skip_trace", False):
                return
            user = self.updated_by or self.created_by
            if creating:
                Movement.record(self, "IN", to_location=self.path, operator=user, reason="Enregistrement de l'aliquot",
                                quantity=self.quantity)
            elif before and (before.box_id, before.position) != (self.box_id, self.position):
                Movement.record(self, "MOVE", from_location=before.path, to_location=self.path, operator=user,
                                reason="Modification de la fiche")


class Movement(LimsModel):
    """Opération sur un aliquot. Les entrées et changements d'emplacement sont aussi tracés automatiquement."""

    url_base = "biobank:movement"

    TYPES = [("IN", "Entrée en biobanque"), ("OUT", "Sortie"), ("RETURN", "Retour en stock"),
             ("THAW", "Décongélation"), ("SHIP", "Transfert / envoi"), ("CONSUME", "Épuisement"),
             ("DESTROY", "Destruction"), ("MOVE", "Changement d'emplacement")]
    NEW_STATUS = {"OUT": "IN_USE", "RETURN": "AVAILABLE", "SHIP": "SHIPPED",
                  "CONSUME": "EXHAUSTED", "DESTROY": "DESTROYED"}
    ENTRIES, EXITS = ("IN", "RETURN"), ("OUT", "SHIP", "CONSUME", "DESTROY")

    item = models.ForeignKey(BiobankItem, verbose_name="aliquot", on_delete=models.CASCADE, related_name="movements")
    type = models.CharField("type de mouvement", max_length=8, choices=TYPES)
    date = models.DateTimeField("date", default=timezone.now)
    quantity = models.DecimalField("quantité prélevée", max_digits=10, decimal_places=2, null=True, blank=True)
    to_box = models.ForeignKey(StorageBox, verbose_name="nouvelle boîte", on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="+",
                               help_text="Changement d'emplacement ou retour en stock")
    to_position = models.CharField("nouvelle position", max_length=5, blank=True)
    from_location = models.CharField("localisation avant", max_length=200, blank=True, editable=False)
    to_location = models.CharField("localisation après", max_length=200, blank=True, editable=False)
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

    @classmethod
    def record(cls, item, type, **fields):
        """Trace une opération déjà appliquée à l'aliquot (sans en rejouer les effets)."""
        mv = cls(item=item, type=type, **fields)
        mv._record_only = True
        mv.created_by = fields.get("operator")
        mv.save()
        return mv

    def clean(self):
        self.to_position = BiobankItem.normalize_position(self.to_position)
        if self.type == "MOVE" and not self.to_box_id:
            raise ValidationError({"to_box": "Indiquez la boîte de destination."})
        if self.to_box_id and self.item_id:
            if not self.to_position:
                raise ValidationError({"to_position": "Indiquez la position dans la boîte."})
            error = self.item.check_position(self.to_box, self.to_position, exclude_pk=self.item_id)
            if error:
                raise ValidationError({"to_position": error})

    def save(self, *args, **kwargs):
        creating = self._state.adding
        if not creating or getattr(self, "_record_only", False):
            return super().save(*args, **kwargs)
        item = self.item
        self.from_location = item.path
        with transaction.atomic():
            if self.type in self.NEW_STATUS:
                item.status = self.NEW_STATUS[self.type]
            if self.type == "THAW":
                item.freeze_thaw += 1
            if self.quantity and item.quantity is not None:
                item.quantity = max(item.quantity - self.quantity, 0)
            if self.to_box_id and self.type in ("MOVE", "RETURN"):
                item.box_id, item.position = self.to_box_id, BiobankItem.normalize_position(self.to_position)
                item.box = self.to_box
            self.to_location = item.path
            item._skip_trace = True
            item.save()
            return super().save(*args, **kwargs)


class BoxMovement(LimsModel):
    """Déplacement d'une boîte entière (autre congélateur, étagère ou rack)."""

    url_base = "biobank:boxmove"

    box = models.ForeignKey(StorageBox, verbose_name="boîte", on_delete=models.CASCADE, related_name="moves")
    date = models.DateTimeField("date", default=timezone.now)
    from_location = models.CharField("localisation avant", max_length=200)
    to_location = models.CharField("localisation après", max_length=200)
    reason = models.CharField("motif", max_length=255, blank=True)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="opérateur", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "déplacement de boîte"
        verbose_name_plural = "déplacements de boîtes"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.box} : {self.from_location} → {self.to_location}"


# ---------------------------------------------------------------------------
# Inventaires physiques
# ---------------------------------------------------------------------------

class InventorySession(CodedModel):
    """Inventaire physique d'un congélateur, d'une étagère, d'un rack ou d'une boîte."""

    url_base = "biobank:inventory"
    code_prefix = "INV"
    code_width = 3

    STATUS = [("OPEN", "En cours"), ("SUBMITTED", "Soumis pour validation"), ("VALIDATED", "Validé"),
              ("CANCELLED", "Annulé")]

    unit = models.ForeignKey(StorageUnit, verbose_name="congélateur", on_delete=models.PROTECT,
                             related_name="inventories")
    shelf = models.CharField("étagère", max_length=30, blank=True, help_text="Vide : tout le congélateur")
    rack = models.CharField("rack", max_length=30, blank=True, help_text="Vide : toute l'étagère")
    box = models.ForeignKey(StorageBox, verbose_name="boîte", on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="inventories", help_text="Vide : tout le rack")
    status = models.CharField("statut", max_length=10, choices=STATUS, default="OPEN")
    started_at = models.DateTimeField("début", default=timezone.now)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="réalisé par", on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="+")
    submitted_at = models.DateTimeField("soumis le", null=True, blank=True, editable=False)
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="validé par", on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="+", editable=False)
    validated_at = models.DateTimeField("validé le", null=True, blank=True, editable=False)
    validation_comment = models.TextField("commentaire du responsable", blank=True, editable=False)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "inventaire"
        verbose_name_plural = "inventaires"
        ordering = ["-started_at"]
        permissions = [("validate_inventorysession", "Peut valider les inventaires de la biobanque")]

    def __str__(self):
        return f"{self.code} — {self.scope}"

    def clean(self):
        self.shelf, self.rack = level_code("E", self.shelf), level_code("R", self.rack)
        if self.box_id and self.box.unit_id != self.unit_id:
            raise ValidationError({"box": "Cette boîte n'est pas dans le congélateur choisi."})

    @property
    def scope(self):
        if self.box_id:
            return self.box.path
        return "/".join(x for x in (self.unit.name, self.shelf, self.rack) if x)

    @property
    def level(self):
        return "Boîte" if self.box_id else "Rack" if self.rack else "Étagère" if self.shelf else "Congélateur"

    def boxes(self):
        if self.box_id:
            return StorageBox.objects.filter(pk=self.box_id)
        qs = StorageBox.objects.filter(unit=self.unit)
        if self.shelf:
            qs = qs.filter(shelf=self.shelf)
        if self.rack:
            qs = qs.filter(rack=self.rack)
        return qs.order_by("shelf", "rack", "name")

    def populate(self):
        """Une ligne par boîte (contrôle de l'étiquette / QR code) et par aliquot attendu."""
        lines = []
        for box in self.boxes():
            lines.append(InventoryLine(session=self, kind="BOX", box=box))
            for item in box.items.exclude(status__in=BiobankItem.GONE).order_by("position"):
                lines.append(InventoryLine(session=self, kind="ITEM", box=box, position=item.position,
                                           expected_item=item))
        InventoryLine.objects.bulk_create(lines)

    def counts(self):
        out = dict.fromkeys(dict(InventoryLine.STATUS), 0)
        for status in self.lines.values_list("status", flat=True):
            out[status] += 1
        return out

    def anomalies(self):
        return self.lines.exclude(status__in=("OK", "PENDING"))


class InventoryLine(LimsModel):
    url_base = "biobank:anomaly"

    KINDS = [("BOX", "Boîte"), ("ITEM", "Aliquot")]
    STATUS = [("PENDING", "À vérifier"), ("OK", "Conforme"), ("MISSING", "Manquant"),
              ("UNREGISTERED", "Non enregistré"), ("MISPLACED", "Mal positionné"),
              ("LABEL", "Étiquette / QR non conforme")]
    ANOMALIES = ("MISSING", "UNREGISTERED", "MISPLACED", "LABEL")

    session = models.ForeignKey(InventorySession, verbose_name="inventaire", on_delete=models.CASCADE,
                                related_name="lines")
    kind = models.CharField("objet", max_length=4, choices=KINDS, default="ITEM")
    box = models.ForeignKey(StorageBox, verbose_name="boîte", on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="+")
    position = models.CharField("position attendue", max_length=5, blank=True)
    expected_item = models.ForeignKey(BiobankItem, verbose_name="aliquot enregistré", on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name="inventory_lines")
    found_code = models.CharField("code lu", max_length=80, blank=True)
    found_position = models.CharField("position constatée", max_length=5, blank=True)
    status = models.CharField("constat", max_length=12, choices=STATUS, default="PENDING")
    comment = models.CharField("commentaire", max_length=255, blank=True)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="vérifié par", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    checked_at = models.DateTimeField("vérifié le", null=True, blank=True)
    corrected = models.BooleanField("position corrigée", default=False)

    class Meta:
        verbose_name = "constat d'inventaire"
        verbose_name_plural = "anomalies d'inventaire"
        ordering = ["session", "box__name", "kind", "position"]

    def __str__(self):
        what = self.expected_item.code if self.expected_item_id else (self.found_code or (self.box.name if self.box_id else ""))
        return f"{self.session.code} · {what} · {self.get_status_display()}"
