from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import LimsModel, TestResult


class Project(LimsModel):
    url_base = "research:project"

    STATUS = [("PLANNED", "Planifié"), ("ACTIVE", "En cours"), ("CLOSED", "Clôturé"), ("SUSPENDED", "Suspendu")]
    code = models.CharField("code projet", max_length=30, unique=True)
    title = models.CharField("titre", max_length=255)
    principal_investigator = models.CharField("investigateur principal", max_length=150)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, verbose_name="membres", blank=True,
                                     related_name="projects")
    funder = models.CharField("financement", max_length=150, blank=True)
    ethics_ref = models.CharField("n° avis éthique", max_length=80, blank=True)
    ethics_expiry = models.DateField("expiration avis éthique", null=True, blank=True)
    start_date = models.DateField("début", null=True, blank=True)
    end_date = models.DateField("fin", null=True, blank=True)
    status = models.CharField("statut", max_length=10, choices=STATUS, default="ACTIVE")
    description = models.TextField("description", blank=True)

    class Meta:
        verbose_name = "projet"
        verbose_name_plural = "projets"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.title}"


class Study(LimsModel):
    """Étude rattachée à un projet (ex. CBC/AUGEN)."""

    url_base = "research:study"

    CASE_MODES = [("PROJECT", "Cas du projet (tous)"), ("LIST", "Cas spécifiques à l'étude"),
                  ("TEXT", "Cas à saisir (texte libre)"), ("NONE", "Pas de cas")]
    project = models.ForeignKey(Project, verbose_name="projet", on_delete=models.CASCADE, related_name="studies")
    code = models.CharField("code", max_length=40)
    name = models.CharField("intitulé", max_length=255, blank=True)
    case_mode = models.CharField("saisie du cas", max_length=8, choices=CASE_MODES, default="PROJECT",
                                 help_text="Comment le cas est renseigné à l'enregistrement d'un échantillon de cette étude.")
    cases = models.ManyToManyField("ProjectCase", verbose_name="cas autorisés", blank=True, related_name="studies",
                                   help_text="Uniquement pour « Cas spécifiques à l'étude » (cas du même projet).")
    case_label = models.CharField("libellé du champ à saisir", max_length=80, blank=True,
                                  help_text="Pour « Cas à saisir », ex. « N° de cas », « Code inclusion »…")
    active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "étude"
        verbose_name_plural = "études"
        ordering = ["project", "code"]
        unique_together = [("project", "code")]

    def __str__(self):
        return f"{self.project.code}/{self.code}"

    def allowed_cases(self):
        """Cas sélectionnables pour cette étude (selon la configuration de l'administrateur)."""
        if self.case_mode == "LIST":
            return self.cases.filter(active=True)
        if self.case_mode == "PROJECT":
            return self.project.cases.filter(active=True)
        return ProjectCase.objects.none()


class ProjectCase(LimsModel):
    """Catégorie de cas d'un projet (ex. cas index, contact, témoin…)."""

    url_base = "research:case"

    project = models.ForeignKey(Project, verbose_name="projet", on_delete=models.CASCADE, related_name="cases")
    name = models.CharField("cas", max_length=120)
    description = models.CharField("description", max_length=255, blank=True)
    active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "cas"
        verbose_name_plural = "cas"
        ordering = ["project", "name"]
        unique_together = [("project", "name")]

    def __str__(self):
        return f"{self.name} ({self.project.code})"


class SequencingRun(LimsModel):
    url_base = "research:run"

    TECHNOLOGIES = [("WGS", "Whole Genome Sequencing (WGS)"), ("TNGS", "Targeted NGS (tNGS)"),
                    ("AMPLICON", "Amplicon / autre")]
    PLATFORMS = [
        ("ONT_MINION", "ONT MinION / Mk1C"),
        ("ONT_GRIDION", "ONT GridION"),
        ("ONT_PROMETHION", "ONT PromethION"),
        ("ILL_ISEQ", "Illumina iSeq 100"),
        ("ILL_MISEQ", "Illumina MiSeq"),
        ("ILL_NEXTSEQ", "Illumina NextSeq"),
        ("ILL_NOVASEQ", "Illumina NovaSeq"),
        ("OTHER", "Autre"),
    ]
    STATUS = [("PLANNED", "Planifié"), ("RUNNING", "En cours"), ("DONE", "Terminé"), ("FAILED", "Échec")]

    run_id = models.CharField("identifiant du run", max_length=60, unique=True)
    technology = models.CharField("technologie", max_length=10, choices=TECHNOLOGIES, default="WGS")
    platform = models.CharField("plateforme", max_length=15, choices=PLATFORMS)
    project = models.ForeignKey(Project, verbose_name="projet", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="runs")
    library_kit = models.CharField("kit de librairie", max_length=100, blank=True,
                                   help_text="Ex. SQK-RBK114.24, Nextera XT, Deeplex Myc-TB")
    flowcell = models.CharField("flowcell / cartouche", max_length=60, blank=True)
    run_date = models.DateField("date du run", default=timezone.localdate)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="opérateur", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="+")
    status = models.CharField("statut", max_length=8, choices=STATUS, default="PLANNED")
    total_yield_gb = models.DecimalField("rendement total (Gb)", max_digits=8, decimal_places=2,
                                         null=True, blank=True)
    data_path = models.CharField("chemin des données brutes", max_length=500, blank=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "run de séquençage"
        verbose_name_plural = "runs de séquençage"
        ordering = ["-run_date"]

    def __str__(self):
        return f"{self.run_id} ({self.get_platform_display()})"


class SequencingLibrary(LimsModel):
    url_base = "research:library"

    run = models.ForeignKey(SequencingRun, verbose_name="run", on_delete=models.CASCADE, related_name="libraries")
    sample = models.ForeignKey("core.Sample", verbose_name="échantillon", on_delete=models.PROTECT,
                               null=True, blank=True, related_name="libraries")
    dna = models.ForeignKey("biobank.BiobankItem", verbose_name="extrait ADN (biobanque)",
                            on_delete=models.SET_NULL, null=True, blank=True, related_name="libraries")
    library_id = models.CharField("identifiant librairie", max_length=60)
    barcode = models.CharField("barcode / index", max_length=60, blank=True)
    input_conc = models.DecimalField("[ADN] entrée (ng/µL)", max_digits=8, decimal_places=2, null=True, blank=True)
    library_conc = models.DecimalField("[librairie] (ng/µL)", max_digits=8, decimal_places=2, null=True, blank=True)
    reads = models.BigIntegerField("nombre de reads", null=True, blank=True)
    mean_depth = models.DecimalField("profondeur moyenne (x)", max_digits=8, decimal_places=1, null=True, blank=True)
    coverage_pct = models.DecimalField("couverture génome (%)", max_digits=5, decimal_places=2, null=True, blank=True)
    qc_pass = models.BooleanField("QC conforme", null=True, blank=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "librairie de séquençage"
        verbose_name_plural = "librairies de séquençage"
        ordering = ["run", "barcode"]
        unique_together = [("run", "library_id")]

    def __str__(self):
        return f"{self.library_id} / {self.run.run_id}"


class PCRRun(LimsModel):
    """Run de RT-qPCR (une plaque, une signature) : regroupe les échantillons analysés."""

    url_base = "research:pcrrun"

    ASSAYS = [("RISK6", "RISK6"), ("SWEENEY3", "Sweeney3"), ("OTHER", "Autre")]
    STATUS = SequencingRun.STATUS

    run_id = models.CharField("identifiant du run / plaque", max_length=60, unique=True)
    assay = models.CharField("signature", max_length=10, choices=ASSAYS)
    project = models.ForeignKey(Project, verbose_name="projet", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="pcr_runs")
    instrument = models.CharField("thermocycleur", max_length=60, blank=True)
    kit_lot = models.CharField("lot du kit", max_length=60, blank=True)
    reference_gene = models.CharField("gène de référence", max_length=30, blank=True)
    threshold = models.DecimalField("seuil de positivité", max_digits=8, decimal_places=3, null=True, blank=True)
    run_date = models.DateField("date du run", default=timezone.localdate)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="opérateur", on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="+")
    status = models.CharField("statut", max_length=8, choices=STATUS, default="PLANNED")
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "run PCR"
        verbose_name_plural = "runs PCR"
        ordering = ["-run_date", "-id"]

    def __str__(self):
        return f"{self.run_id} ({self.get_assay_display()})"

    @property
    def n_results(self):
        return self.results.count()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        for result in self.results.exclude(result_status="VALIDATED"):  # signature, seuil ou date modifiés
            result.save()


class PCRAssay(TestResult):
    """Résultat d'un échantillon dans un run PCR (signatures RISK6, Sweeney3)."""

    url_base = "research:pcr"

    OUTCOMES = [("POS", "Signature positive"), ("NEG", "Signature négative"), ("NA", "Non déterminé")]

    run = models.ForeignKey(PCRRun, verbose_name="run PCR", on_delete=models.PROTECT, related_name="results")
    ref_ct = models.DecimalField("Ct référence", max_digits=5, decimal_places=2, null=True, blank=True)
    # RISK6
    ct_gbp2 = models.DecimalField("Ct GBP2", max_digits=5, decimal_places=2, null=True, blank=True)
    ct_fcgr1b = models.DecimalField("Ct FCGR1B", max_digits=5, decimal_places=2, null=True, blank=True)
    ct_serping1 = models.DecimalField("Ct SERPING1", max_digits=5, decimal_places=2, null=True, blank=True)
    ct_tubgcp6 = models.DecimalField("Ct TUBGCP6", max_digits=5, decimal_places=2, null=True, blank=True)
    ct_trmt2a = models.DecimalField("Ct TRMT2A", max_digits=5, decimal_places=2, null=True, blank=True)
    ct_sdr39u1 = models.DecimalField("Ct SDR39U1", max_digits=5, decimal_places=2, null=True, blank=True)
    # Sweeney3
    ct_gbp5 = models.DecimalField("Ct GBP5", max_digits=5, decimal_places=2, null=True, blank=True)
    ct_dusp3 = models.DecimalField("Ct DUSP3", max_digits=5, decimal_places=2, null=True, blank=True)
    ct_klf2 = models.DecimalField("Ct KLF2", max_digits=5, decimal_places=2, null=True, blank=True)

    score = models.DecimalField("score", max_digits=8, decimal_places=3, null=True, blank=True,
                                help_text="Sweeney3 : calculé automatiquement. RISK6 : saisir le score du logiciel.")
    outcome = models.CharField("conclusion", max_length=3, choices=OUTCOMES, default="NA", editable=False)

    class Meta(TestResult.Meta):
        verbose_name = "PCR signature"
        verbose_name_plural = "PCR signatures"

    def __str__(self):
        return f"{self.run.get_assay_display()} — {self.sample.code}"

    def compute(self):
        # Sweeney3 = moy(expr GBP5, DUSP3) − expr KLF2, avec expr = −ΔCt ;
        # le Ct de référence s'annule : score = Ct_KLF2 − (Ct_GBP5 + Ct_DUSP3) / 2
        if self.run.assay == "SWEENEY3" and None not in (self.ct_gbp5, self.ct_dusp3, self.ct_klf2):
            self.score = (self.ct_klf2 - (self.ct_gbp5 + self.ct_dusp3) / Decimal(2)).quantize(Decimal("0.001"))
        if self.score is not None and self.run.threshold is not None:
            self.outcome = "POS" if self.score >= self.run.threshold else "NEG"
        else:
            self.outcome = "NA"

    def save(self, *args, **kwargs):
        self.compute()
        self.test_date = self.run.run_date   # la date d'analyse est celle du run
        if not self.performed_by_id:
            self.performed_by = self.run.operator
        super().save(*args, **kwargs)


class LPATest(TestResult):
    """Line Probe Assay — Hain GenoType MTBDRplus / MTBDRsl / CM-AS."""

    url_base = "research:lpa"

    KITS = [("PLUS", "GenoType MTBDRplus v2"), ("SL", "GenoType MTBDRsl v2"),
            ("CMAS", "GenoType Mycobacterium CM / AS"), ("NTMDR", "GenoType NTM-DR")]
    SOURCES = [("DIRECT", "Échantillon direct"), ("CULTURE", "Culture / isolat")]
    INTERP = [("S", "Sensible"), ("R", "Résistant"), ("IND", "Indéterminé"), ("NA", "Non testé")]

    project = models.ForeignKey(Project, verbose_name="projet", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="lpa_tests")
    kit = models.CharField("kit", max_length=5, choices=KITS)
    kit_lot = models.CharField("lot du kit", max_length=30, blank=True)
    source = models.CharField("matériel testé", max_length=8, choices=SOURCES, default="CULTURE")
    mtbc_detected = models.BooleanField("MTBC détecté", null=True, blank=True)
    species = models.CharField("espèce identifiée", max_length=100, blank=True, help_text="CM/AS, NTM-DR")
    rif = models.CharField("RIF (rpoB)", max_length=3, choices=INTERP, default="NA")
    inh_katg = models.CharField("INH haut niveau (katG)", max_length=3, choices=INTERP, default="NA")
    inh_inha = models.CharField("INH bas niveau (inhA)", max_length=3, choices=INTERP, default="NA")
    fq = models.CharField("FQ (gyrA / gyrB)", max_length=3, choices=INTERP, default="NA")
    sli = models.CharField("Injectables (rrs / eis)", max_length=3, choices=INTERP, default="NA")
    missing_wt = models.CharField("bandes WT absentes", max_length=255, blank=True)
    mutations = models.CharField("bandes MUT présentes", max_length=255, blank=True,
                                 help_text="Ex. rpoB MUT3 (S450L), katG MUT1 (S315T1)")

    class Meta(TestResult.Meta):
        verbose_name = "LPA (Hain)"
        verbose_name_plural = "LPA (Hain)"

    def __str__(self):
        return f"{self.get_kit_display()} — {self.sample.code}"


# ---------------------------------------------------------------------------
# Cahiers de laboratoire
# ---------------------------------------------------------------------------

class LabNotebook(LimsModel):
    """Registre des cahiers de laboratoire (papier ou électroniques) ; les pages électroniques sont des entrées."""

    url_base = "research:notebook"

    KINDS = [("PAPER", "Papier (scanné ou non)"), ("ELEC", "Électronique (entrées MYCOGEN)")]
    STATUS = [("OPEN", "En cours"), ("CLOSED", "Clôturé"), ("ARCHIVED", "Archivé")]

    code = models.CharField("n° du cahier", max_length=30, unique=True, help_text="Ex. CL-2026-014")
    title = models.CharField("titre / objet", max_length=200)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="titulaire", on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="lab_notebooks")
    project = models.ForeignKey(Project, verbose_name="projet", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="notebooks")
    domain = models.CharField("domaine / activité", max_length=100, blank=True,
                              help_text="Ex. Biologie moléculaire, Culture, Bioinformatique")
    kind = models.CharField("support", max_length=5, choices=KINDS, default="PAPER")
    status = models.CharField("statut", max_length=8, choices=STATUS, default="OPEN")
    started_on = models.DateField("ouvert le", default=timezone.localdate)
    closed_on = models.DateField("clôturé le", null=True, blank=True)
    location = models.CharField("emplacement physique", max_length=150, blank=True,
                                help_text="Salle, armoire, étagère (cahiers papier)")
    scan = models.FileField("cahier scanné (PDF)", upload_to="research/notebooks/%Y/", blank=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "cahier de laboratoire"
        verbose_name_plural = "cahiers de laboratoire"
        ordering = ["-started_on", "code"]

    def __str__(self):
        return f"{self.code} — {self.title}"


class NotebookEntry(LimsModel):
    """Page / entrée datée d'un cahier de laboratoire."""

    url_base = "research:entry"

    notebook = models.ForeignKey(LabNotebook, verbose_name="cahier", on_delete=models.CASCADE, related_name="entries")
    date = models.DateField("date", default=timezone.localdate)
    title = models.CharField("titre", max_length=200)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="auteur", on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="notebook_entries")
    content = models.TextField("contenu", blank=True, help_text="Objectif, protocole, observations, résultats")
    attachment = models.FileField("pièce jointe", upload_to="research/notebooks/entries/%Y/", blank=True)

    class Meta:
        verbose_name = "entrée de cahier"
        verbose_name_plural = "entrées de cahier"
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.date:%d/%m/%Y} — {self.title}"


# ---------------------------------------------------------------------------
# MycoLearn : supports visuels d'apprentissage
# ---------------------------------------------------------------------------

class LearningDomain(LimsModel):
    """Sous-domaine de MycoLearn (Bioinformatique, Biologie moléculaire, Immunologie…)."""

    url_base = "research:domain"

    name = models.CharField("domaine", max_length=80, unique=True)
    icon = models.CharField("icône", max_length=40, default="bi-mortarboard",
                            help_text="Nom d'icône Bootstrap Icons, ex. bi-dna")
    description = models.CharField("description", max_length=255, blank=True)
    order = models.PositiveSmallIntegerField("ordre d'affichage", default=100)

    class Meta:
        verbose_name = "domaine MycoLearn"
        verbose_name_plural = "domaines MycoLearn"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class LearningResource(LimsModel):
    """Support d'apprentissage : vidéo, présentation, PDF, infographie ou lien."""

    url_base = "research:learning"

    KINDS = [("VIDEO", "Vidéo"), ("SLIDES", "Présentation"), ("PDF", "Document PDF"), ("IMAGE", "Image / infographie"),
             ("LINK", "Lien web"), ("TUTO", "Tutoriel / exercice")]
    LEVELS = [("BEG", "Débutant"), ("INT", "Intermédiaire"), ("ADV", "Avancé")]
    VIDEO_EXT = (".mp4", ".webm", ".ogg", ".mov")
    IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")

    title = models.CharField("titre", max_length=200)
    domain = models.ForeignKey(LearningDomain, verbose_name="domaine", on_delete=models.PROTECT,
                               related_name="resources")
    kind = models.CharField("type de support", max_length=6, choices=KINDS, default="PDF")
    level = models.CharField("niveau", max_length=3, choices=LEVELS, default="BEG")
    file = models.FileField("fichier", upload_to="mycolearn/%Y/", blank=True,
                            help_text="Vidéo (MP4), présentation, PDF ou image")
    url = models.URLField("lien", blank=True, help_text="Vidéo en ligne, cours, article…")
    thumbnail = models.ImageField("vignette", upload_to="mycolearn/vignettes/", blank=True)
    description = models.TextField("description", blank=True)
    author = models.CharField("auteur / source", max_length=150, blank=True)
    duration_min = models.PositiveSmallIntegerField("durée (min)", null=True, blank=True)
    published = models.BooleanField("publié", default=True, help_text="Décocher pour masquer le support")

    class Meta:
        verbose_name = "support MycoLearn"
        verbose_name_plural = "supports MycoLearn"
        ordering = ["domain__order", "title"]

    def __str__(self):
        return self.title

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.file and not self.url:
            raise ValidationError("Joignez un fichier ou indiquez un lien.")

    @property
    def file_ext(self):
        return ("." + self.file.name.rsplit(".", 1)[-1].lower()) if self.file and "." in self.file.name else ""

    @property
    def is_video(self):
        return self.file_ext in self.VIDEO_EXT

    @property
    def is_image(self):
        return self.file_ext in self.IMAGE_EXT

    @property
    def is_pdf(self):
        return self.file_ext == ".pdf"
