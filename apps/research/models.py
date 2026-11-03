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


class PCRAssay(TestResult):
    """Signatures transcriptionnelles par RT-qPCR (RISK6, Sweeney3)."""

    url_base = "research:pcr"

    ASSAYS = [("RISK6", "RISK6"), ("SWEENEY3", "Sweeney3"), ("OTHER", "Autre")]
    OUTCOMES = [("POS", "Signature positive"), ("NEG", "Signature négative"), ("NA", "Non déterminé")]

    project = models.ForeignKey(Project, verbose_name="projet", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="pcr_assays")
    assay = models.CharField("signature", max_length=10, choices=ASSAYS)
    instrument = models.CharField("thermocycleur", max_length=60, blank=True)
    plate_id = models.CharField("plaque / run", max_length=60, blank=True)
    reference_gene = models.CharField("gène de référence", max_length=30, blank=True)
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
    threshold = models.DecimalField("seuil de positivité", max_digits=8, decimal_places=3, null=True, blank=True)
    outcome = models.CharField("conclusion", max_length=3, choices=OUTCOMES, default="NA", editable=False)

    class Meta(TestResult.Meta):
        verbose_name = "PCR signature"
        verbose_name_plural = "PCR signatures"

    def __str__(self):
        return f"{self.get_assay_display()} — {self.sample.code}"

    def compute(self):
        # Sweeney3 = moy(expr GBP5, DUSP3) − expr KLF2, avec expr = −ΔCt ;
        # le Ct de référence s'annule : score = Ct_KLF2 − (Ct_GBP5 + Ct_DUSP3) / 2
        if self.assay == "SWEENEY3" and None not in (self.ct_gbp5, self.ct_dusp3, self.ct_klf2):
            self.score = (self.ct_klf2 - (self.ct_gbp5 + self.ct_dusp3) / Decimal(2)).quantize(Decimal("0.001"))
        if self.score is not None and self.threshold is not None:
            self.outcome = "POS" if self.score >= self.threshold else "NEG"
        else:
            self.outcome = "NA"

    def save(self, *args, **kwargs):
        self.compute()
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
