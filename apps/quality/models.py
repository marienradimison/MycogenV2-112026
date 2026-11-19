from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import LimsModel

SOON_DAYS = 30  # échéances signalées « à venir » dans les 30 jours


def due_state(date):
    """'overdue' | 'soon' | 'ok' | None pour une date d'échéance."""
    if not date:
        return None
    today = timezone.localdate()
    if date < today:
        return "overdue"
    if date <= today + timedelta(days=SOON_DAYS):
        return "soon"
    return "ok"


class Equipment(LimsModel):
    """Matériel d'une salle, avec suivi de maintenance et d'étalonnage / qualification."""

    url_base = "quality:equipment"

    CATEGORIES = [
        ("PSM", "Poste de sécurité microbiologique / hotte"), ("CENTRIF", "Centrifugeuse"),
        ("INCUB", "Incubateur / étuve"), ("COLD", "Réfrigérateur / congélateur"), ("MICRO", "Microscope"),
        ("ANALYZER", "Automate d'analyse"), ("PCR", "Thermocycleur / qPCR"), ("SEQ", "Séquenceur"),
        ("AUTOCLAVE", "Autoclave"), ("BALANCE", "Balance"), ("PIPETTE", "Pipettes / petit matériel"),
        ("SAFETY", "Sécurité (extincteur, douche, lave-œil…)"), ("IT", "Informatique"),
        ("FURNITURE", "Mobilier"), ("OTHER", "Autre"),
    ]
    STATUS = [("OK", "En service"), ("MAINT", "En maintenance"), ("DOWN", "En panne"),
              ("QUARANTINE", "Hors usage (quarantaine)"), ("RETIRED", "Réformé")]

    room = models.ForeignKey("core.Room", verbose_name="salle", on_delete=models.PROTECT, related_name="equipment")
    name = models.CharField("désignation", max_length=150)
    category = models.CharField("catégorie", max_length=10, choices=CATEGORIES, default="OTHER")
    inventory_number = models.CharField("n° d'inventaire", max_length=60, blank=True)
    brand = models.CharField("marque", max_length=80, blank=True)
    model_name = models.CharField("modèle", max_length=80, blank=True)
    serial_number = models.CharField("n° de série", max_length=80, blank=True)
    status = models.CharField("état", max_length=10, choices=STATUS, default="OK")
    critical = models.BooleanField("équipement critique", default=False,
                                   help_text="Impact direct sur les résultats ou la sécurité")
    commissioned_on = models.DateField("mise en service", null=True, blank=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="référent", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="equipment")
    supplier = models.CharField("fournisseur / maintenance", max_length=150, blank=True)
    maintenance_interval_months = models.PositiveSmallIntegerField("périodicité maintenance (mois)", null=True, blank=True)
    last_maintenance = models.DateField("dernière maintenance", null=True, blank=True)
    next_maintenance = models.DateField("prochaine maintenance", null=True, blank=True,
                                        help_text="Calculée automatiquement si une périodicité est indiquée")
    calibration_interval_months = models.PositiveSmallIntegerField("périodicité étalonnage / qualification (mois)",
                                                                   null=True, blank=True)
    last_calibration = models.DateField("dernier étalonnage / qualification", null=True, blank=True)
    next_calibration = models.DateField("prochain étalonnage / qualification", null=True, blank=True,
                                        help_text="Calculé automatiquement si une périodicité est indiquée")
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "matériel"
        verbose_name_plural = "matériels"
        ordering = ["room__number", "name"]
        permissions = [("view_sgq", "Consulter le SGQ (statistiques et indicateurs de performance)")]

    def __str__(self):
        return f"{self.name}" + (f" ({self.inventory_number})" if self.inventory_number else "")

    @staticmethod
    def add_months(d, months):
        y, m = divmod(d.month - 1 + months, 12)
        import calendar
        day = min(d.day, calendar.monthrange(d.year + y, m + 1)[1])
        return d.replace(year=d.year + y, month=m + 1, day=day)

    def save(self, *args, **kwargs):
        if self.last_maintenance and self.maintenance_interval_months:
            self.next_maintenance = self.add_months(self.last_maintenance, self.maintenance_interval_months)
        if self.last_calibration and self.calibration_interval_months:
            self.next_calibration = self.add_months(self.last_calibration, self.calibration_interval_months)
        super().save(*args, **kwargs)

    @property
    def maintenance_state(self):
        return due_state(self.next_maintenance) if self.status != "RETIRED" else None

    @property
    def calibration_state(self):
        return due_state(self.next_calibration) if self.status != "RETIRED" else None

    @property
    def alert(self):
        """Niveau d'alerte global : 'danger', 'warning' ou ''."""
        if self.status in ("DOWN", "QUARANTINE") or "overdue" in (self.maintenance_state, self.calibration_state):
            return "danger"
        if self.status == "MAINT" or "soon" in (self.maintenance_state, self.calibration_state):
            return "warning"
        return ""


class RoomAccess(LimsModel):
    """Autorisation d'accès d'une personne à une salle."""

    url_base = "quality:access"

    LEVELS = [("FULL", "Accès autorisé"), ("ESCORT", "Accès accompagné"), ("MAINT", "Maintenance / intervention")]

    room = models.ForeignKey("core.Room", verbose_name="salle", on_delete=models.CASCADE, related_name="accesses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur MYCOGEN", on_delete=models.CASCADE,
                             null=True, blank=True, related_name="room_accesses")
    person_name = models.CharField("personne (sans compte)", max_length=150, blank=True,
                                   help_text="Prestataire, visiteur… si la personne n'a pas de compte MYCOGEN")
    function = models.CharField("fonction", max_length=100, blank=True)
    level = models.CharField("type d'accès", max_length=6, choices=LEVELS, default="FULL")
    granted_on = models.DateField("autorisé le", default=timezone.localdate)
    expires_on = models.DateField("valable jusqu'au", null=True, blank=True)
    training_on = models.DateField("formation (biosécurité…) le", null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="autorisé par", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    revoked = models.BooleanField("révoqué", default=False)
    notes = models.CharField("remarques", max_length=255, blank=True)

    class Meta:
        verbose_name = "accès à une salle"
        verbose_name_plural = "accès aux salles"
        ordering = ["room__number", "user__last_name", "person_name"]

    def __str__(self):
        return f"{self.person} → salle {self.room.number}"

    @property
    def person(self):
        if self.user:
            return self.user.get_full_name() or self.user.username
        return self.person_name or "?"

    def clean(self):
        if not self.user and not self.person_name:
            raise ValidationError("Choisissez un utilisateur ou indiquez le nom de la personne.")
        if self.user and RoomAccess.objects.filter(room=self.room_id, user=self.user, revoked=False) \
                .exclude(pk=self.pk).exists():
            raise ValidationError({"user": "Cette personne a déjà un accès actif à cette salle."})

    @property
    def valid(self):
        return not self.revoked and (not self.expires_on or self.expires_on >= timezone.localdate())

    @property
    def state(self):
        if self.revoked:
            return "revoked"
        st = due_state(self.expires_on)
        return {"overdue": "expired", "soon": "soon"}.get(st, "valid")


class QualityDocument(LimsModel):
    """DQ — documents qualité : manuels qualité, procédures, SOP, manuels clients, formulaires, communiqués…
    Chaque version est une fiche ; l'approbation est signée (signature de l'approbateur) et archive
    automatiquement la version précédente en vigueur de la même référence."""

    url_base = "quality:document"

    CATEGORIES = [
        ("MQ", "Manuel qualité"), ("PROC", "Procédure"), ("SOP", "Mode opératoire (SOP)"),
        ("MC", "Manuel client / de prélèvement"), ("FORM", "Formulaire / fiche d'enregistrement"),
        ("INSTR", "Instruction / affiche"), ("COMM", "Communiqué / note de service"),
        ("REC", "Rapport / enregistrement qualité"), ("EXT", "Document externe (norme, guide)"), ("OTHER", "Autre"),
    ]
    STATUS = [("DRAFT", "Brouillon"), ("REVIEW", "En vérification"), ("APPROVED", "En vigueur (approuvé)"),
              ("ARCHIVED", "Archivé / obsolète")]

    reference = models.CharField("référence", max_length=40, help_text="Ex. MYC-SOP-012, MYC-MQ-001")
    title = models.CharField("titre", max_length=200)
    category = models.CharField("type de document", max_length=5, choices=CATEGORIES, default="SOP")
    version = models.CharField("version", max_length=10, default="01")
    status = models.CharField("statut", max_length=8, choices=STATUS, default="DRAFT")
    file = models.FileField("fichier", upload_to="quality/documents/%Y/", blank=True,
                            help_text="PDF de préférence (Word, Excel, images acceptés)")
    summary = models.TextField("objet / résumé", blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="rédacteur", on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="authored_quality_documents")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="vérificateur", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="reviewed_quality_documents")
    distribution = models.CharField("diffusion", max_length=255, blank=True,
                                    help_text="Postes, salles ou destinataires concernés")
    effective_on = models.DateField("date d'application", null=True, blank=True,
                                    help_text="Par défaut : date d'approbation")
    next_review = models.DateField("prochaine revue", null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="approuvé par", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="approved_quality_documents", editable=False)
    approved_at = models.DateTimeField("approuvé le", null=True, blank=True, editable=False)
    approval_comment = models.TextField("commentaire d'approbation", blank=True, editable=False)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "document qualité"
        verbose_name_plural = "documents qualité"
        ordering = ["category", "reference", "-version"]
        constraints = [models.UniqueConstraint(fields=["reference", "version"], name="quality_document_version")]
        permissions = [("approve_qualitydocument", "Approuver et signer les documents qualité")]

    def __str__(self):
        return f"{self.reference} v{self.version} — {self.title}"

    def save(self, *args, **kwargs):
        """Une nouvelle version (fichier ou n° de version modifié) d'un document approuvé repart en brouillon."""
        if self.pk and self.approved_at:
            old = QualityDocument.objects.filter(pk=self.pk).values("version", "file").first()
            if old and (old["version"] != self.version or old["file"] != (self.file.name or "")):
                self.status, self.approved_by, self.approved_at, self.approval_comment = "DRAFT", None, None, ""
        if self.status == "APPROVED" and not self.approved_at:   # « en vigueur » seulement par approbation signée
            self.status = "REVIEW"
        super().save(*args, **kwargs)

    def approve(self, user, comment=""):
        self.status = "APPROVED"
        self.approved_by = user
        self.approved_at = timezone.now()
        self.approval_comment = (comment or "").strip()
        self.effective_on = self.effective_on or timezone.localdate()
        self.updated_by = user
        super().save()
        QualityDocument.objects.filter(reference=self.reference, status="APPROVED").exclude(pk=self.pk) \
            .update(status="ARCHIVED", updated_at=timezone.now())

    @property
    def review_state(self):
        return due_state(self.next_review) if self.status == "APPROVED" else None
