from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from .floorplan import ZONE_CHOICES


class LimsModel(models.Model):
    """Base de tous les objets du LIMS : traçabilité + URL générique.

    `url_base` = "<namespace>:<prefix>" utilisé par les vues CRUD (core/crud.py).
    """

    url_base = None

    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="créé par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+", editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="modifié par", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+", editable=False,
    )

    class Meta:
        abstract = True

    def get_absolute_url(self):
        return reverse(f"{self.url_base}_detail", args=[self.pk])


def next_code(model, field, prefix, width=5, lock=True):
    """Prochain code séquentiel `<prefix><n>` (ex. 26-0042), calculé numériquement (26-9999 → 26-10000)."""
    qs = model.objects.filter(**{f"{field}__startswith": prefix})
    if lock:
        # select_for_update ne verrouille que les lignes existantes : deux saisies simultanées (premier code de
        # l'année, ou code non unique comme celui du patient) obtiendraient le même numéro. Sous PostgreSQL, un
        # verrou consultatif propre à (table, préfixe), libéré au commit, sérialise l'attribution.
        from django.db import connection
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"{model._meta.db_table}:{prefix}"])
        qs = qs.select_for_update()
    numbers = [int(c[len(prefix):]) for c in qs.values_list(field, flat=True) if c[len(prefix):].isdigit()]
    return f"{prefix}{(max(numbers) + 1) if numbers else 1:0{width}d}"


class CodedModel(LimsModel):
    """Objet avec un code unique généré automatiquement."""

    code_prefix = "X"
    code_width = 5
    code = models.CharField("code", max_length=30, unique=True, blank=True)

    class Meta:
        abstract = True

    def build_prefix(self):
        return f"{self.code_prefix}{timezone.localdate():%y}-"

    def save(self, *args, **kwargs):
        if not self.code:
            with transaction.atomic():
                self.code = next_code(type(self), "code", self.build_prefix(), self.code_width)
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Référentiels
# ---------------------------------------------------------------------------

class Facility(LimsModel):
    url_base = "core:facility"

    TYPES = [
        ("CDT", "Centre de Diagnostic et de Traitement (CDT)"),
        ("CSB", "Centre de Santé de Base"),
        ("CHU", "CHU / Hôpital"),
        ("LAB", "Laboratoire"),
        ("CBC", "Centre de Biologie Clinique"),
        ("RECH", "Site de recherche"),
        ("AUTRE", "Autre"),
    ]
    code = models.CharField("code", max_length=20, unique=True)
    name = models.CharField("nom", max_length=200)
    type = models.CharField("type", max_length=10, choices=TYPES, default="CDT")
    region = models.CharField("région", max_length=100, blank=True)
    district = models.CharField("district", max_length=100, blank=True)
    contact = models.CharField("contact", max_length=200, blank=True)
    active = models.BooleanField("actif", default=True)
    notes = models.CharField("remarques / source", max_length=255, blank=True)

    class Meta:
        verbose_name = "structure de provenance"
        verbose_name_plural = "structures de provenance"
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Room(LimsModel):
    """Salle de l'unité, placée sur un emplacement (zone) du plan de masse."""

    url_base = "core:room"

    USAGES = [
        ("LAB", "Laboratoire"), ("BSL3", "Laboratoire P3 / confiné"), ("MOL", "Biologie moléculaire"),
        ("RECEP", "Réception des échantillons"), ("STORE", "Stockage / biobanque"), ("OFFICE", "Bureau"),
        ("MEETING", "Salle de réunion"), ("TECH", "Local technique"), ("SANIT", "Sanitaires / vestiaires"),
        ("OTHER", "Autre"),
    ]
    COLORS = {"LAB": "#6eafc4", "BSL3": "#d0574a", "MOL": "#8a6bbf", "RECEP": "#e8a33d", "STORE": "#3f8197",
              "OFFICE": "#7eaa2f", "MEETING": "#c7b04a", "TECH": "#8c9aa1", "SANIT": "#b9c7cc", "OTHER": "#a0a0a0"}

    zone = models.CharField("emplacement sur le plan", max_length=5, unique=True, choices=ZONE_CHOICES,
                            help_text="Repère de la zone sur le plan (N = côté nord, S = côté sud)")
    number = models.CharField("n° de salle", max_length=20, unique=True)
    name = models.CharField("nom", max_length=120, blank=True)
    usage = models.CharField("usage", max_length=7, choices=USAGES, blank=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="responsable", on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="rooms")
    phone_ext = models.CharField("poste téléphonique", max_length=20, blank=True)
    area_m2 = models.DecimalField("surface (m²)", max_digits=6, decimal_places=1, null=True, blank=True)
    access = models.CharField("accès / restrictions", max_length=150, blank=True,
                              help_text="Ex. accès badge, EPI obligatoires")
    active = models.BooleanField("en service", default=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "salle"
        verbose_name_plural = "salles (plan de masse)"
        ordering = ["number"]

    def __str__(self):
        return f"Salle {self.number}" + (f" — {self.name}" if self.name else "")

    @property
    def color(self):
        return self.COLORS.get(self.usage, "#c3ced2")


class AnalysisCode(LimsModel):
    """Bibliothèque des codes d'analyse (GNX-RIF, FLUO-AUR, Cult-LJ…), utilisés dans les tableaux
    et comme liste des analyses demandables à l'enregistrement d'un échantillon."""

    url_base = "core:code"

    KINDS = [
        ("XPERT_ULTRA", "GeneXpert MTB/RIF Ultra"), ("XPERT_XDR", "GeneXpert XDR"),
        ("MICROSCOPY", "Microscopie"), ("CULTURE", "Culture"), ("DST", "Antibiogramme"),
        ("NPOC", "NPOC"), ("QFT", "QuantiFERON-TB"), ("WGS", "Séquençage"), ("OTHER", "Autre"),
    ]
    METHODS = [("", "—"), ("FM", "Fluorescence"), ("ZN", "Ziehl-Neelsen"), ("LJ", "LJ"), ("MGIT", "MGIT")]

    CATEGORIES = [("ANALYSIS", "Analyse"), ("RESULT", "Résultat"), ("DRUG", "Antibiotique"),
                  ("SUSCEPT", "Résistance aux antibiotiques"), ("INDIC", "Indicateur (SGQ)"),
                  ("ROLE", "Rôle (permissions)")]
    RESULT_CATEGORIES = ("RESULT", "DRUG", "SUSCEPT")

    category = models.CharField("catégorie", max_length=8, choices=CATEGORIES, default="ANALYSIS")
    code = models.CharField("code", max_length=20, unique=True)
    meaning = models.CharField("signification", max_length=150)
    kind = models.CharField("famille d'analyse", max_length=11, choices=KINDS, blank=True,
                            help_text="Analyses : relie le code aux résultats saisis dans Mycogen")
    group = models.OneToOneField("auth.Group", verbose_name="groupe de permissions", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="role_code",
                                 help_text="Rôles : groupe Django portant les permissions du rôle")
    method = models.CharField("méthode / milieu", max_length=4, choices=METHODS, blank=True)
    scope = models.CharField("s'applique à", max_length=120, blank=True,
                             help_text="Codes de résultat : famille d'analyse et méthode / milieu concernées, "
                                       "ex. « Microscopie/Culture — Fluorescence/LJ »")
    order = models.PositiveSmallIntegerField("ordre d'affichage", default=100)
    requestable = models.BooleanField("proposé à l'enregistrement", default=True)
    active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "code d'analyse"
        verbose_name_plural = "bibliothèque de codes"
        ordering = ["order", "code"]

    def __str__(self):
        return f"{self.code} — {self.meaning}"

    @classmethod
    def catalog(cls):
        """{code: AnalysisCode} des codes actifs, dans l'ordre d'affichage (mis en cache par requête)."""
        return {c.code: c for c in cls.objects.filter(active=True, category="ANALYSIS")}

    @classmethod
    def result_catalog(cls):
        """{code: AnalysisCode} des codes de résultat actifs (résultats, antibiotiques, R/S)."""
        return {c.code: c for c in cls.objects.filter(active=True, category__in=cls.RESULT_CATEGORIES)}

    @classmethod
    def for_result(cls, obj, catalog=None):
        """Code correspondant à un résultat saisi (ex. microscopie ZN → « ZN »)."""
        kind, method = result_kind(obj)
        catalog = catalog if catalog is not None else cls.catalog()
        for c in catalog.values():
            if c.kind == kind and (not c.method or c.method == method):
                return c
        return None


def result_kind(obj):
    """(famille, méthode) d'un objet résultat."""
    name = obj._meta.model_name
    if name == "genexperttest":
        return ("XPERT_XDR" if obj.assay == "XDR" else "XPERT_ULTRA"), ""
    if name == "microscopy":
        return "MICROSCOPY", obj.method
    if name == "culture":
        return "CULTURE", obj.medium
    if name == "dst":
        return "DST", obj.method
    if name == "npoctest":
        return "NPOC", ""
    if name == "quantiferon":
        return "QFT", ""
    if name in ("sequencinglibrary", "analysis"):
        return "WGS", ""
    return "OTHER", ""


class Patient(CodedModel):
    url_base = "core:patient"
    code_prefix = "PT"
    code = models.CharField("identifiant externe", max_length=30, blank=True, db_index=True,
                            help_text="Peut être partagé par plusieurs patients (ex. n° de registre du CDT)")

    SEX = [("M", "Masculin"), ("F", "Féminin"), ("I", "Indéterminé")]
    HIV = [("POS", "Positif"), ("NEG", "Négatif"), ("INC", "Inconnu")]
    TB_HISTORY = [
        ("NEW", "Nouveau cas"),
        ("REL", "Rechute"),
        ("FAIL", "Échec"),
        ("LTFU", "Reprise après perte de vue"),
        ("CONTACT", "Contact"),
        ("OTHER", "Autre / inconnu"),
    ]

    last_name = models.CharField("nom", max_length=100)
    first_name = models.CharField("prénoms", max_length=150, blank=True)
    sex = models.CharField("sexe", max_length=1, choices=SEX)
    birth_date = models.DateField("date de naissance", null=True, blank=True)
    age_years = models.PositiveSmallIntegerField("âge (ans)", null=True, blank=True,
                                                 help_text="Si la date de naissance est inconnue")
    national_id = models.CharField("n° CIN / identifiant", max_length=50, blank=True)
    tb_register_number = models.CharField("n° registre TB", max_length=50, blank=True)
    phone = models.CharField("téléphone", max_length=30, blank=True)
    address = models.CharField("adresse", max_length=255, blank=True)
    district = models.CharField("district", max_length=100, blank=True)
    region = models.CharField("région", max_length=100, blank=True)
    hiv_status = models.CharField("statut VIH", max_length=3, choices=HIV, default="INC")
    tb_history = models.CharField("antécédent TB", max_length=10, choices=TB_HISTORY, default="NEW")
    research_consent = models.BooleanField("consentement recherche", default=False)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "patient"
        verbose_name_plural = "patients"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.full_name} ({self.code})"

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name}".strip()

    @staticmethod
    def split_name(full):
        """« RAKOTO Jean Hery » → (« RAKOTO », « Jean Hery ») : les mots en majuscules forment le nom."""
        words = full.split()
        upper = [w for w in words if w.isupper() and len(w) > 1]
        if upper and len(upper) < len(words):
            return " ".join(upper), " ".join(w for w in words if w not in upper)
        return (words[0].upper(), " ".join(words[1:])) if words else ("", "")

    @property
    def age(self):
        if self.birth_date:
            today = timezone.localdate()
            return today.year - self.birth_date.year - (
                (today.month, today.day) < (self.birth_date.month, self.birth_date.day))
        return self.age_years


class Sample(CodedModel):
    """Prélèvement / échantillon reçu au CNRM. N° au format année-numéro : 26-0001."""

    url_base = "core:sample"
    code_width = 4
    code = models.CharField("N° échantillon", max_length=30, unique=True, blank=True)

    TYPES = [
        ("SPUTUM", "Crachat"),
        ("BAL", "Liquide broncho-alvéolaire (LBA)"),
        ("GASTRIC_LAV", "Tubage gastrique"),
        ("GASTRIC_ASP", "Aspiration gastrique"),
        ("PLEURAL", "Liquide pleural"),
        ("ASCITIC", "Liquide d'ascite"),
        ("PERICARDIAL", "Liquide péricardique"),
        ("SYNOVIAL", "Liquide synovial"),
        ("CSF", "Liquide céphalo-rachidien (LCR)"),
        ("CEREBROSPINAL", "Liquide cérébro-spinal"),
        ("PUS", "Pus"),
        ("BIOPSY", "Biopsie"),
        ("SWAB", "Écouvillon"),
        ("URINE", "Urine"),
        ("STOOL", "Selles"),
        ("OTHER", "Autres"),
    ]
    # Suggestions pour le champ libre « aspect » (crachat, liquides, urines…)
    ASPECTS = ["Salivaire", "Muqueux", "Muco-purulent", "Purulent", "Sanglant", "Hémorragique", "Clair",
               "Trouble", "Jaune", "Citrin", "Louche", "Visqueux"]
    HOSTS = ["Humain", "Bovin", "Porcin", "Ovin", "Caprin", "Canin", "Félin", "Faune sauvage"]
    PULMONARY = {"SPUTUM", "BAL", "GASTRIC_LAV", "GASTRIC_ASP"}
    REASONS = [
        ("DIAG", "Diagnostic"),
        ("FU", "Suivi de traitement"),
        ("DST", "Recherche de résistance"),
        ("SURV", "Surveillance / enquête"),
        ("RES", "Recherche"),
        ("EQA", "Contrôle qualité (EEQ)"),
    ]
    FOLLOWUP = [("", "—"), ("M2", "M2"), ("M3", "M3"), ("M5", "M5"), ("M6", "M6"), ("END", "Fin de traitement")]
    STATUS = [
        ("RECEIVED", "Reçu"),
        ("IN_PROGRESS", "En cours d'analyse"),
        ("PENDING_VALIDATION", "En attente de validation"),
        ("COMPLETED", "Terminé"),
        ("REJECTED", "Rejeté"),
    ]
    CODE_RE = r"^\d{2}-\d{4,}$"

    patient = models.ForeignKey(Patient, verbose_name="patient", on_delete=models.PROTECT,
                                null=True, blank=True, related_name="samples")
    facility = models.ForeignKey(Facility, verbose_name="provenance / CDT", on_delete=models.PROTECT,
                                 null=True, blank=True, related_name="samples")
    project = models.ForeignKey("research.Project", verbose_name="projet",
                                on_delete=models.SET_NULL, null=True, blank=True, related_name="samples")
    study = models.ForeignKey("research.Study", verbose_name="étude", on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="samples")
    case_text = models.CharField("cas (saisi)", max_length=120, blank=True,
                                 help_text="Pour les études dont le cas est saisi au lieu d'être choisi dans une liste.")
    case = models.ForeignKey("research.ProjectCase", verbose_name="cas", on_delete=models.SET_NULL,
                             null=True, blank=True, related_name="samples")
    external_id = models.CharField("n° bon de demande / réf.", max_length=60, blank=True,
                                   help_text="N° du bon de demande, référence du laboratoire d'origine…")
    host = models.CharField("hôte", max_length=60, blank=True, default="Humain",
                            help_text="Humain, bovin… : hôte dont provient l'échantillon")
    sample_type = models.CharField("type de prélèvement", max_length=13, choices=TYPES, default="SPUTUM")
    type_detail = models.CharField("précision", max_length=120, blank=True,
                                   help_text="Ex. 2 mL, lobe inférieur droit, ganglion cervical…")
    aspect = models.CharField("aspect", max_length=60, blank=True, help_text="Aspect de l'échantillon")
    volume_ml = models.DecimalField("volume (mL)", max_digits=6, decimal_places=2, null=True, blank=True)
    reason = models.CharField("motif", max_length=5, choices=REASONS, default="DIAG")
    followup_month = models.CharField("mois de suivi", max_length=3, choices=FOLLOWUP, blank=True)
    collected_at = models.DateTimeField("date de prélèvement", null=True, blank=True)
    received_at = models.DateTimeField("date de réception", default=timezone.now)
    requester = models.CharField("prescripteur", max_length=150, blank=True)
    requester_contact = models.CharField("contact prescripteur", max_length=120, blank=True,
                                         help_text="Téléphone ou e-mail du prescripteur")
    requested_analyses = models.JSONField("analyses demandées", default=list, blank=True)
    conform = models.BooleanField("conforme", default=True)
    non_conformity = models.CharField("motif de non-conformité", max_length=255, blank=True)
    status = models.CharField("statut", max_length=20, choices=STATUS, default="RECEIVED", editable=False)
    notes = models.TextField("remarques", blank=True)
    legacy_ref = models.CharField("réf. ancien LIMS", max_length=40, blank=True, db_index=True, editable=False,
                                  help_text="Identifiant de la fiche reprise de l'ancien LIMS")

    class Meta:
        verbose_name = "échantillon"
        verbose_name_plural = "échantillons"
        ordering = ["-received_at"]
        permissions = [("validate_results", "Peut valider les résultats"),
                       ("view_validation", "Peut consulter et exporter la table de validation")]

    def build_prefix(self):
        return f"{timezone.localdate():%y}-"

    @classmethod
    def next_code(cls, year=None):
        year = year if year is not None else timezone.localdate().year
        return next_code(cls, "code", f"{year % 100:02d}-", cls.code_width, lock=False)

    def __str__(self):
        return f"{self.code} ({self.get_sample_type_display()})"

    @property
    def type_display(self):
        label = self.get_sample_type_display()
        return f"{label} ({self.type_detail})" if self.type_detail else label

    @property
    def tb_form(self):
        """Forme de tuberculose déduite du type de prélèvement."""
        return "Pulmonaire" if self.sample_type in self.PULMONARY else "Extrapulmonaire"

    @property
    def case_display(self):
        return self.case.name if self.case_id else self.case_text

    @property
    def analyses_display(self):
        """Codes des analyses demandées (bibliothèque de codes), ex. « GNX-RIF, FLUO-AUR »."""
        return ", ".join(self.requested_analyses or [])

# ---------------------------------------------------------------------------
# Résultat d'analyse (base abstraite) avec circuit de validation
# ---------------------------------------------------------------------------

class TestResult(LimsModel):
    STATUS = [("DRAFT", "Saisi"), ("VALIDATED", "Validé"), ("CANCELLED", "Annulé")]

    sample = models.ForeignKey(Sample, verbose_name="échantillon", on_delete=models.PROTECT,
                               related_name="%(class)s_set")
    test_date = models.DateField("date d'analyse", default=timezone.localdate)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="réalisé par",
                                     on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    result_status = models.CharField("statut", max_length=10, choices=STATUS, default="DRAFT")
    validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="validé par",
                                     on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", editable=False)
    validated_at = models.DateTimeField("validé le", null=True, blank=True, editable=False)
    validation_comment = models.TextField("commentaire du validateur", blank=True, editable=False)
    comment = models.TextField("commentaire", blank=True)

    validatable = True

    class Meta:
        abstract = True
        ordering = ["-test_date", "-id"]

    def validate(self, user, comment=""):
        self.result_status = "VALIDATED"
        self.validated_by = user
        self.validated_at = timezone.now()
        self.validation_comment = (comment or "").strip()
        self.save(update_fields=["result_status", "validated_by", "validated_at", "validation_comment", "updated_at"])

    @property
    def is_validated(self):
        return self.result_status == "VALIDATED"


# ---------------------------------------------------------------------------
# Compte utilisateur : préférences, support
# ---------------------------------------------------------------------------

class UserProfile(models.Model):
    THEMES = [("light", "Clair"), ("dark", "Sombre"), ("auto", "Automatique (système)")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    photo = models.ImageField("photo de profil", upload_to="avatars/", blank=True)
    theme = models.CharField("thème", max_length=5, choices=THEMES, default="light")
    job_title = models.CharField("poste", max_length=100, blank=True,
                                 help_text="Titre affiché (ex. Technicienne de laboratoire). N'accorde aucun droit : "
                                           "les permissions viennent des rôles.")
    phone = models.CharField("téléphone", max_length=30, blank=True)
    signature = models.ImageField("signature", upload_to="signatures/", blank=True,
                                  help_text="Image de la signature manuscrite (PNG à fond transparent de préférence). "
                                            "Apposée sur les résultats validés, les documents qualité et les communiqués.")
    signature_label = models.CharField("mention sous la signature", max_length=150, blank=True,
                                       help_text="Ex. « Dr Rakoto, Médecin biologiste ». Par défaut : nom et poste.")

    class Meta:
        verbose_name = "profil utilisateur"
        verbose_name_plural = "profils utilisateurs"

    def __str__(self):
        return f"Profil de {self.user}"

    @property
    def signature_caption(self):
        if self.signature_label:
            return self.signature_label
        name = self.user.get_full_name() or self.user.username
        return f"{name}, {self.job_title}" if self.job_title else name

    @property
    def initials(self):
        u = self.user
        letters = (u.first_name[:1] + u.last_name[:1]) or u.username[:2]
        return letters.upper()


class BugReport(models.Model):
    SEVERITY = [("LOW", "Mineur"), ("MEDIUM", "Gênant"), ("HIGH", "Bloquant")]
    STATUS = [("OPEN", "Ouvert"), ("IN_PROGRESS", "En cours"), ("RESOLVED", "Résolu"), ("CLOSED", "Fermé")]

    created_at = models.DateTimeField("signalé le", auto_now_add=True)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="signalé par", on_delete=models.SET_NULL,
                                 null=True, related_name="bug_reports")
    title = models.CharField("titre", max_length=150)
    description = models.TextField("description", help_text="Ce que vous faisiez, ce qui s'est passé, ce qui était attendu")
    page = models.CharField("page concernée", max_length=300, blank=True)
    severity = models.CharField("gravité", max_length=6, choices=SEVERITY, default="MEDIUM")
    screenshot = models.ImageField("capture d'écran", upload_to="bugs/", blank=True)
    status = models.CharField("statut", max_length=12, choices=STATUS, default="OPEN")
    response = models.TextField("réponse de l'administrateur", blank=True)

    class Meta:
        verbose_name = "rapport de bug"
        verbose_name_plural = "rapports de bug"
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"


class PasswordResetRequest(models.Model):
    STATUS = [("OPEN", "En attente"), ("DONE", "Traitée"), ("REJECTED", "Refusée")]

    created_at = models.DateTimeField("demandé le", auto_now_add=True)
    username = models.CharField("identifiant saisi", max_length=150)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.CASCADE,
                             null=True, blank=True, related_name="reset_requests")
    message = models.CharField("message", max_length=255, blank=True)
    status = models.CharField("statut", max_length=8, choices=STATUS, default="OPEN")
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="traitée par", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    handled_at = models.DateTimeField("traitée le", null=True, blank=True)

    class Meta:
        verbose_name = "demande de réinitialisation"
        verbose_name_plural = "demandes de réinitialisation de mot de passe"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.username} ({self.get_status_display()})"


class ActivityLog(models.Model):
    """Journal d'audit des actions utilisateurs."""

    ACTIONS = [("CREATE", "Création"), ("UPDATE", "Modification"), ("DELETE", "Suppression"),
               ("VALIDATE", "Validation")]
    timestamp = models.DateTimeField("date", auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur",
                             on_delete=models.SET_NULL, null=True)
    action = models.CharField("action", max_length=10, choices=ACTIONS)
    model = models.CharField("objet", max_length=100)
    object_id = models.CharField("id", max_length=40)
    object_repr = models.CharField("description", max_length=255)
    changes = models.JSONField("modifications", default=dict, blank=True)

    class Meta:
        verbose_name = "journal d'activité"
        verbose_name_plural = "journal d'activité"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.user} {self.action} {self.object_repr}"
