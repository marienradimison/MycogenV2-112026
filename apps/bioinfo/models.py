from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import CodedModel, LimsModel


class Pipeline(LimsModel):
    url_base = "bioinfo:pipeline"

    name = models.CharField("nom", max_length=100)
    version = models.CharField("version", max_length=30)
    tool_type = models.CharField("type", max_length=100, blank=True,
                                 help_text="Ex. profilage de résistance, lignée, phylogénie, assemblage")
    reference = models.CharField("génome de référence", max_length=100, default="H37Rv (NC_000962.3)")
    database_version = models.CharField("version base de mutations", max_length=60, blank=True,
                                        help_text="Ex. catalogue OMS 2023, TBDB")
    repository = models.CharField("dépôt / URL", max_length=255, blank=True)
    active = models.BooleanField("en usage", default=True)
    description = models.TextField("description", blank=True)

    class Meta:
        verbose_name = "pipeline"
        verbose_name_plural = "pipelines"
        ordering = ["name", "-version"]
        unique_together = [("name", "version")]

    def __str__(self):
        return f"{self.name} v{self.version}"


class Analysis(CodedModel):
    url_base = "bioinfo:analysis"
    code_prefix = "BI"

    STATUS = [("QUEUED", "En attente"), ("RUNNING", "En cours"), ("DONE", "Terminée"), ("FAILED", "Échec"),
              ("REVIEWED", "Revue / validée")]
    PROFILES = [
        ("", "—"),
        ("SENSITIVE", "Sensible"),
        ("HR", "Hr-TB (INH résistant)"),
        ("RR", "RR-TB"),
        ("MDR", "MDR-TB"),
        ("PREXDR", "Pré-XDR-TB"),
        ("XDR", "XDR-TB"),
        ("OTHER", "Autre résistance"),
    ]

    library = models.ForeignKey("research.SequencingLibrary", verbose_name="librairie séquencée",
                                on_delete=models.PROTECT, null=True, blank=True, related_name="analyses")
    sample = models.ForeignKey("core.Sample", verbose_name="échantillon", on_delete=models.PROTECT,
                               null=True, blank=True, related_name="analyses")
    pipeline = models.ForeignKey(Pipeline, verbose_name="pipeline", on_delete=models.PROTECT, related_name="analyses")
    analyst = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="analyste", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="+")
    run_date = models.DateField("date d'analyse", default=timezone.localdate)
    status = models.CharField("statut", max_length=8, choices=STATUS, default="QUEUED")
    species = models.CharField("espèce", max_length=100, blank=True, default="M. tuberculosis")
    lineage = models.CharField("lignée", max_length=30, blank=True, help_text="Ex. 1, 2, 4")
    sublineage = models.CharField("sous-lignée", max_length=50, blank=True, help_text="Ex. 4.1.2.1")
    spoligotype = models.CharField("spoligotype (SIT)", max_length=50, blank=True)
    drug_profile = models.CharField("profil de résistance", max_length=10, choices=PROFILES, blank=True)
    resistance_mutations = models.TextField("mutations de résistance", blank=True,
                                            help_text="Une par ligne : gène  mutation  antibiotique  (fréquence)")
    mean_depth = models.DecimalField("profondeur moyenne (x)", max_digits=8, decimal_places=1, null=True, blank=True)
    genome_coverage = models.DecimalField("génome couvert (%)", max_digits=5, decimal_places=2, null=True, blank=True)
    mapped_pct = models.DecimalField("reads mappés (%)", max_digits=5, decimal_places=2, null=True, blank=True)
    cluster = models.CharField("cluster de transmission", max_length=50, blank=True,
                               help_text="Seuil SNP utilisé à préciser en remarque")
    output_path = models.CharField("dossier de résultats", max_length=500, blank=True)
    report_file = models.FileField("rapport (fichier)", upload_to="bioinfo/reports/%Y/", blank=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "analyse génomique"
        verbose_name_plural = "analyses génomiques"
        ordering = ["-run_date", "-id"]

    def __str__(self):
        target = self.sample.code if self.sample else (self.library.library_id if self.library else "?")
        return f"{self.code} — {target}"

    def save(self, *args, **kwargs):
        if self.library_id and not self.sample_id and self.library.sample_id:
            self.sample_id = self.library.sample_id
        super().save(*args, **kwargs)
