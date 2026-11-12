from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TestResult

RES_DETECTION = [
    ("DETECTED", "Détecté"),
    ("NOT_DETECTED", "Non détecté"),
    ("INDETERMINATE", "Indéterminé"),
    ("NA", "Non applicable"),
]


class GeneXpertTest(TestResult):
    url_base = "diagnostic:genexpert"

    ASSAYS = [("ULTRA", "Xpert MTB/RIF Ultra"), ("XDR", "Xpert MTB/XDR")]
    MTB = [
        ("NOT_DETECTED", "MTB non détecté"),
        ("TRACE", "MTB détecté — traces"),
        ("VERY_LOW", "MTB détecté — très faible"),
        ("LOW", "MTB détecté — faible"),
        ("MEDIUM", "MTB détecté — moyen"),
        ("HIGH", "MTB détecté — élevé"),
        ("VERY_HIGH", "MTB détecté — très élevé"),
        ("DETECTED", "MTB détecté"),
        ("INVALID", "Invalide"),
        ("ERROR", "Erreur"),
        ("NO_RESULT", "Pas de résultat"),
    ]

    assay = models.CharField("test", max_length=5, choices=ASSAYS, default="ULTRA")
    cartridge_lot = models.CharField("lot cartouche", max_length=30, blank=True)
    instrument = models.CharField("appareil / module", max_length=50, blank=True)
    mtb_result = models.CharField("résultat MTB", max_length=15, choices=MTB)
    rif_result = models.CharField("résistance RIF", max_length=15, choices=RES_DETECTION, default="NA",
                                  help_text="Xpert Ultra")
    # Xpert MTB/XDR
    inh_result = models.CharField("résistance INH", max_length=15, choices=RES_DETECTION, default="NA")
    fq_result = models.CharField("résistance FQ", max_length=15, choices=RES_DETECTION, default="NA")
    amk_result = models.CharField("résistance AMK", max_length=15, choices=RES_DETECTION, default="NA")
    kan_result = models.CharField("résistance KAN", max_length=15, choices=RES_DETECTION, default="NA")
    cap_result = models.CharField("résistance CAP", max_length=15, choices=RES_DETECTION, default="NA")
    eto_result = models.CharField("résistance ETH", max_length=15, choices=RES_DETECTION, default="NA")
    error_code = models.CharField("code erreur", max_length=20, blank=True)

    class Meta(TestResult.Meta):
        verbose_name = "test GeneXpert"
        verbose_name_plural = "tests GeneXpert"

    def __str__(self):
        return f"{self.get_assay_display()} — {self.sample.code}"

    @property
    def xdr_values(self):
        """Résultats XDR dans l'ordre INH, FLQ, AMK, KAN, CAP, ETH."""
        return [self.inh_result, self.fq_result, self.amk_result, self.kan_result, self.cap_result, self.eto_result]

    @property
    def mtb_positive(self):
        return self.mtb_result in ("TRACE", "VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "DETECTED")


class NPOCTest(TestResult):
    """Test moléculaire NPOC (near point-of-care) — Pluslife MiniDock MTB."""

    url_base = "diagnostic:npoc"

    ASSAYS = [("PLUSLIFE_MTB", "Pluslife MTB")]
    RESULTS = [
        ("DETECTED", "MTB détecté"),
        ("NOT_DETECTED", "MTB non détecté"),
        ("INVALID", "Invalide"),
        ("ERROR", "Erreur"),
    ]
    assay = models.CharField("test", max_length=15, choices=ASSAYS, default="PLUSLIFE_MTB")
    device_serial = models.CharField("n° série appareil", max_length=50, blank=True)
    kit_lot = models.CharField("lot du kit", max_length=30, blank=True)
    mtb_result = models.CharField("résultat MTB", max_length=15, choices=RESULTS)
    signal_value = models.DecimalField("valeur de signal (Tt / Ct)", max_digits=6, decimal_places=2,
                                       null=True, blank=True)
    error_code = models.CharField("code erreur", max_length=30, blank=True)

    class Meta(TestResult.Meta):
        verbose_name = "test NPOC (Pluslife)"
        verbose_name_plural = "tests NPOC (Pluslife)"

    def __str__(self):
        return f"{self.get_assay_display()} — {self.sample.code}"


class Microscopy(TestResult):
    url_base = "diagnostic:microscopy"

    METHODS = [("ZN", "Ziehl-Neelsen"), ("FM", "Fluorescence (Auramine / LED)")]
    GRADES = [
        ("NEG", "Négatif (0 BAAR)"),
        ("SCANTY", "Rares BAAR"),
        ("1+", "1+"),
        ("2+", "2+"),
        ("3+", "3+"),
        ("NA", "Non interprétable"),
    ]
    method = models.CharField("méthode", max_length=2, choices=METHODS, default="FM")
    slide_number = models.CharField("n° lame", max_length=30, blank=True)
    grade = models.CharField("résultat", max_length=6, choices=GRADES)
    afb_count = models.PositiveSmallIntegerField("nombre de BAAR", null=True, blank=True,
                                                 help_text="Pour un résultat « rares BAAR »")

    class Meta(TestResult.Meta):
        verbose_name = "microscopie"
        verbose_name_plural = "microscopies"

    def __str__(self):
        return f"Microscopie {self.get_method_display()} — {self.sample.code}"


class Culture(TestResult):
    url_base = "diagnostic:culture"

    MEDIA = [("LJ", "Löwenstein-Jensen (LJ)"), ("MGIT", "MGIT 960 (liquide)")]
    DECONTAMINATION = [("NALC", "NALC-NaOH"), ("PETROFF", "Petroff (NaOH 4 %)"), ("NONE", "Aucune"),
                       ("OTHER", "Autre")]
    RESULTS = [
        ("PENDING", "En cours"),
        ("POSITIVE", "Positive"),
        ("NEGATIVE", "Négative"),
        ("CONTAMINATED", "Contaminée"),
    ]
    LJ_GRADES = [("", "—"), ("1-19", "1–19 colonies (noter le nombre)"), ("1+", "1+ (20–100)"),
                 ("2+", "2+ (100–200)"), ("3+", "3+ (> 200)")]
    IDS = [
        ("", "—"),
        ("MTBC", "Complexe M. tuberculosis"),
        ("NTM", "Mycobactérie non tuberculeuse (MNT)"),
        ("NON_MTBC", "Non CMTB — identification LPA en attente"),
        ("MIXED", "Mixte MTBC + MNT"),
        ("NON_MYCO", "Non mycobactérie"),
    ]
    medium = models.CharField("milieu", max_length=4, choices=MEDIA)
    TUBE_COUNTS = [(1, "1"), (2, "2")]
    tube_count = models.PositiveSmallIntegerField("nombre de tubes", choices=TUBE_COUNTS, default=2)
    tube_number = models.CharField("code-barres du tube (automate MGIT)", max_length=30, blank=True, editable=False)
    decontamination = models.CharField("décontamination", max_length=8, choices=DECONTAMINATION, default="NALC")
    inoculated_on = models.DateField("date d'ensemencement (mise en étuve)")
    result = models.CharField("résultat", max_length=12, choices=RESULTS, default="PENDING")
    result_date = models.DateField("date du résultat", null=True, blank=True,
                                   help_text="Obligatoire dès qu'un résultat est rendu ; le délai de positivité en découle")
    ttp_days = models.DecimalField("délai de positivité (j)", max_digits=5, decimal_places=1,
                                   null=True, blank=True, editable=False,
                                   help_text="Calculé automatiquement : date du résultat − date d'ensemencement")
    lj_grade = models.CharField("cotation LJ", max_length=4, choices=LJ_GRADES, blank=True)
    colony_count = models.PositiveSmallIntegerField("nombre de colonies", null=True, blank=True)
    zn_confirmation = models.BooleanField("BAAR confirmés au ZN", null=True, blank=True)
    identification = models.CharField("identification", max_length=10, choices=IDS, blank=True)
    id_method = models.CharField("méthode d'identification", max_length=60, blank=True,
                                 help_text="Ex. MPT64 (TBc ID), Hain CM/AS")
    # Suivi en étuve (LJ)
    SD_RESULTS = [("", "—"), ("POS", "Positif (CMTB)"), ("NEG", "Négatif (non CMTB)")]
    RETREAT = [("", "—"), ("TO_RETREAT", "À retraiter"), ("RETREATED", "Retraité")]
    incubator = models.ForeignKey("quality.Equipment", verbose_name="étuve", on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name="cultures",
                                  limit_choices_to={"category": "INCUB"})
    growth_on = models.DateField("pousse détectée le", null=True, blank=True)
    sd_test = models.CharField("test SD (MPT64)", max_length=3, choices=SD_RESULTS, blank=True)
    sd_date = models.DateField("date du test SD", null=True, blank=True)
    retreat_status = models.CharField("retraitement", max_length=10, choices=RETREAT, blank=True)
    retreat_of = models.ForeignKey("self", verbose_name="retraitement de", on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="retreatments")

    LJ_TUBES = 2  # valeur par défaut du nombre de tubes
    NEGATIVE_AFTER_DAYS = 90
    GROWTH_MIN_DAYS = 21

    class Meta(TestResult.Meta):
        verbose_name = "culture"
        verbose_name_plural = "cultures"

    @property
    def age_days(self):
        from django.utils import timezone
        end = self.result_date if self.result != "PENDING" and self.result_date else timezone.localdate()
        return (end - self.inoculated_on).days if self.inoculated_on else None

    @property
    def retreated_on(self):
        """Date de retraitement = date d'ensemencement de la nouvelle culture."""
        new = self.retreatments.order_by("inoculated_on").first()
        return new.inoculated_on if new else None

    def sync_tubes(self):
        """Ajuste les tubes au nombre indiqué (ajout d'un tube, ou retrait d'un tube encore en étuve)."""
        if self.medium != "LJ":
            return
        tubes = {t.number: t for t in self.tubes.all()}
        for n in range(1, self.tube_count + 1):
            if n not in tubes:
                CultureTube.objects.create(culture=self, number=n,
                                           status="INCUB" if self.result == "PENDING" else "EXITED")
        for n, t in tubes.items():
            if n > self.tube_count and t.status == "INCUB":
                t.delete()

    @property
    def tubes_display(self):
        parts = []
        for t in self.tubes.all():
            s = f"T{t.number} {t.get_status_display().lower()}"
            if t.status == "CONTAMINATED" and t.status_date:
                s += f" {t.status_date:%d/%m}"
            parts.append(s)
        return " · ".join(parts)

    @property
    def stage(self):
        """(code, libellé) de l'étape de suivi de la culture."""
        if self.result == "NEGATIVE":
            return "NEG", "Négative"
        if self.result == "CONTAMINATED":
            return ("RETREAT", "Contaminée — à retraiter") if self.retreat_status == "TO_RETREAT" else ("CONT", "Contaminée")
        if self.result == "POSITIVE":
            if self.identification == "NON_MTBC":
                return "LPA", "Non CMTB — LPA à faire"
            return "POS", "Positive" + (" CMTB" if self.identification == "MTBC" else "")
        if self.growth_on and not self.sd_test:
            return "SD", "Pousse — test SD à faire"
        if (self.age_days or 0) >= self.NEGATIVE_AFTER_DAYS:
            return "EXIT", f"≥ {self.NEGATIVE_AFTER_DAYS} j — sortie négative"
        return "INCUB", "En étuve"

    def __str__(self):
        return f"Culture {self.medium} — {self.sample.code}"

    def compute_ttp(self):
        """Délai de positivité (jours) = date du résultat − date d'ensemencement, pour une culture positive."""
        if self.result == "POSITIVE" and self.result_date and self.inoculated_on:
            days = (self.result_date - self.inoculated_on).days
            return Decimal(days) if days >= 0 else None
        return None

    def clean(self):
        super().clean()
        if self.result != "PENDING" and not self.result_date:
            raise ValidationError({"result_date": "Indiquez la date du résultat (sert au calcul du délai de positivité)."})
        if self.result_date and self.inoculated_on and self.result_date < self.inoculated_on:
            raise ValidationError({"result_date": "La date du résultat précède la date d'ensemencement."})

    def save(self, *args, **kwargs):
        from datetime import date
        to_date = lambda v: date.fromisoformat(v) if isinstance(v, str) else v  # noqa: E731
        self.result_date, self.inoculated_on = to_date(self.result_date), to_date(self.inoculated_on)
        self.ttp_days = self.compute_ttp()
        if kwargs.get("update_fields") is not None and "ttp_days" not in kwargs["update_fields"]:
            kwargs["update_fields"] = list(kwargs["update_fields"]) + ["ttp_days"]
        if self.inoculated_on:  # la date d'analyse d'une culture est sa date d'ensemencement
            self.test_date = self.inoculated_on
            if kwargs.get("update_fields") is not None and "test_date" not in kwargs["update_fields"]:
                kwargs["update_fields"] = list(kwargs["update_fields"]) + ["test_date"]
        super().save(*args, **kwargs)
        if kwargs.get("update_fields") is None:
            self.sync_tubes()


class CultureTube(models.Model):
    """Tube d'une culture LJ (2 tubes par échantillon), suivi individuellement en étuve."""

    STATUS = [("INCUB", "En étuve"), ("GROWTH", "Pousse"), ("CONTAMINATED", "Contaminé — jeté"),
              ("EXITED", "Sorti")]
    culture = models.ForeignKey(Culture, on_delete=models.CASCADE, related_name="tubes")
    number = models.PositiveSmallIntegerField("tube")
    status = models.CharField("état", max_length=12, choices=STATUS, default="INCUB")
    status_date = models.DateField("date", null=True, blank=True)

    class Meta:
        verbose_name = "tube de culture"
        ordering = ["culture", "number"]
        unique_together = [("culture", "number")]

    def __str__(self):
        return f"Tube {self.number} — {self.get_status_display()}"

    @property
    def active(self):
        return self.status in ("INCUB", "GROWTH")


class IncubatorReading(models.Model):
    """Lecture hebdomadaire d'étuve (culture LJ)."""

    date = models.DateField("date de lecture")
    incubator = models.ForeignKey("quality.Equipment", verbose_name="étuve", on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name="readings")
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="lecteur", on_delete=models.SET_NULL,
                                 null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "lecture d'étuve"
        verbose_name_plural = "lectures d'étuve"
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Lecture du {self.date:%d/%m/%Y}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("diagnostic:lj_reading", args=[self.pk])


class ReadingEntry(models.Model):
    OBS = [("", "—"), ("NOGROWTH", "Pas de pousse"), ("GROWTH", "Pousse"), ("CONTAMINATED", "Contaminé")]
    MORPHOLOGY = [("E", "Eugonique"), ("d", "Dysgonique"), ("R", "Rugueux"), ("s", "Lisse")]
    SD_SIGNS = [("+", "+"), ("-", "−")]
    CONCLUSIONS = [("CMTB", "CMTB"), ("ATYP", "Atypique")]
    PIGMENTS = ["Non pigmenté", "Beige", "Crème", "Jaune", "Orange"]
    BAAR_ASPECTS = ["id BK", "Court", "Long", "Fin", "Trapu", "Coccobacille"]
    ACTIONS = [
        ("NONE", "Reste en étuve"), ("TUBE_DISCARDED", "Tube contaminé jeté"),
        ("GROWTH_SD", "Pousse — test SD à faire"), ("POSITIVE", "Positive CMTB — sortie"),
        ("NON_MTBC", "Non CMTB — identification LPA"), ("NEGATIVE", "Négative — sortie"),
        ("RETREAT", "Contaminée — à retraiter"),
    ]
    reading = models.ForeignKey(IncubatorReading, on_delete=models.CASCADE, related_name="entries")
    culture = models.ForeignKey(Culture, on_delete=models.CASCADE, related_name="reading_entries")
    age_days = models.PositiveSmallIntegerField("âge (j)")
    tube1 = models.CharField("tube 1", max_length=12, choices=OBS, blank=True)
    tube2 = models.CharField("tube 2", max_length=12, choices=OBS, blank=True)
    sd_test = models.CharField("test SD", max_length=3, choices=Culture.SD_RESULTS, blank=True)
    action = models.CharField("décision", max_length=14, choices=ACTIONS, default="NONE")
    discarded_tubes = models.CharField("tubes jetés", max_length=10, blank=True)
    # Fiche de lecture (MYC-FIC-008) : renseignée pour chaque échantillon
    colonies = models.CharField("nombre de colonies", max_length=5, blank=True,
                                help_text="0, nombre exact de colonies, 100, 200 ou 300")
    morphology = models.CharField("morphologie", max_length=4, blank=True, help_text="E, d, R, s")
    pigment = models.CharField("pigment", max_length=60, blank=True)
    baar_aspect = models.CharField("aspect BAAR (ZN)", max_length=80, blank=True)
    sd_control = models.CharField("SD MPT64 — contrôle", max_length=1, choices=SD_SIGNS, blank=True)
    conclusion = models.CharField("conclusion", max_length=4, choices=CONCLUSIONS, blank=True)
    cj_lj = models.BooleanField("CJ — LJ", default=False)
    cj_pyr = models.BooleanField("CJ — Pyr", default=False)

    class Meta:
        verbose_name = "ligne de lecture"
        ordering = ["reading", "culture__sample__code"]

    @property
    def growth_days(self):
        """Temps de croissance : de l'ensemencement à la pousse, sinon à la date de lecture."""
        c = self.culture
        end = self.reading.date
        if c.growth_on and c.growth_on <= end:
            end = c.growth_on
        return (end - c.inoculated_on).days

    @property
    def sd_sign(self):
        return {"POS": "+", "NEG": "−"}.get(self.sd_test, "")

    @property
    def control_sign(self):
        return {"+": "+", "-": "−"}.get(self.sd_control, "")


class TemperatureLog(models.Model):
    """Relevé de température d'une étuve (fiche de suivi)."""

    TARGET_MIN, TARGET_MAX = Decimal("36.0"), Decimal("38.0")
    incubator = models.ForeignKey("quality.Equipment", verbose_name="étuve", on_delete=models.CASCADE,
                                  related_name="temperatures")
    measured_at = models.DateTimeField("relevé le")
    value = models.DecimalField("température (°C)", max_digits=4, decimal_places=1)
    operator = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="relevé par", on_delete=models.SET_NULL,
                                 null=True, related_name="+")
    comment = models.CharField("commentaire / action corrective", max_length=255, blank=True)

    class Meta:
        verbose_name = "relevé de température"
        verbose_name_plural = "relevés de température"
        ordering = ["-measured_at"]

    @property
    def out_of_range(self):
        return not (self.TARGET_MIN <= self.value <= self.TARGET_MAX)


class DST(TestResult):
    """Antibiogramme phénotypique, saisi par groupe d'antibiotiques :
    première ligne (SIRE + PZA) ou seconde ligne ; un résultat R / S / I / NF / NA par antibiotique."""

    url_base = "diagnostic:dst"

    DRUGS = [
        ("STR", "Streptomycine"), ("INH", "Isoniazide"), ("RIF", "Rifampicine"), ("EMB", "Éthambutol"),
        ("PZA", "Pyrazinamide"),
        ("LFX", "Lévofloxacine"), ("MFX", "Moxifloxacine"), ("AMK", "Amikacine"), ("BDQ", "Bédaquiline"),
        ("LZD", "Linézolide"), ("CFZ", "Clofazimine"), ("DLM", "Délamanide"), ("PMD", "Prétomanide"),
        ("ETO", "Éthionamide"), ("INH_H", "Isoniazide (haute conc.)"),
    ]
    PANELS = [("FIRST", "Première ligne (SIRE + PZA)"), ("SECOND", "Seconde ligne")]
    PANEL_DRUGS = {
        "FIRST": ["STR", "INH", "RIF", "EMB", "PZA"],
        "SECOND": ["LFX", "MFX", "AMK", "BDQ", "LZD", "CFZ", "DLM", "PMD", "ETO", "INH_H"],
    }
    RESULTS = [("R", "Résistant"), ("S", "Sensible"), ("I", "Indéterminé"), ("NF", "Non fait"),
               ("NA", "Non applicable")]
    METHODS = [("MGIT", "MGIT 960"), ("LJ", "LJ — méthode des proportions"), ("MIC", "CMI (microdilution)")]

    culture = models.ForeignKey(Culture, verbose_name="culture", on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="dsts")
    method = models.CharField("méthode", max_length=4, choices=METHODS, default="MGIT")
    panel = models.CharField("groupe", max_length=6, choices=PANELS, default="FIRST")
    results = models.JSONField("résultats par antibiotique", default=dict, blank=True)

    class Meta(TestResult.Meta):
        verbose_name = "antibiogramme (DST)"
        verbose_name_plural = "antibiogrammes (DST)"

    def __str__(self):
        return f"DST {'1re' if self.panel == 'FIRST' else '2e'} ligne — {self.sample.code}"

    @property
    def drug_results(self):
        """[(code, antibiotique, résultat, libellé)] dans l'ordre du groupe."""
        names, labels = dict(self.DRUGS), dict(self.RESULTS)
        return [(d, names[d], self.results.get(d, ""), labels.get(self.results.get(d, ""), "—"))
                for d in self.PANEL_DRUGS.get(self.panel, [])]

    @property
    def results_display(self):
        return " · ".join(f"{d} {r}" for d, _, r, _ in self.drug_results if r) or "—"

    @property
    def resistant(self):
        return [d for d, _, r, _ in self.drug_results if r == "R"]

class Quantiferon(TestResult):
    """QuantiFERON-TB Gold Plus — interprétation automatique selon l'algorithme Qiagen."""

    url_base = "diagnostic:quantiferon"

    INTERPRETATIONS = [("POS", "Positif"), ("NEG", "Négatif"), ("IND", "Indéterminé")]
    kit_lot = models.CharField("lot du kit", max_length=30, blank=True)
    nil = models.DecimalField("Nil (UI/mL)", max_digits=6, decimal_places=3)
    tb1 = models.DecimalField("TB1 (UI/mL)", max_digits=6, decimal_places=3)
    tb2 = models.DecimalField("TB2 (UI/mL)", max_digits=6, decimal_places=3)
    mitogen = models.DecimalField("Mitogène (UI/mL)", max_digits=6, decimal_places=3)
    interpretation = models.CharField("interprétation", max_length=3, choices=INTERPRETATIONS,
                                      blank=True, editable=False)

    class Meta(TestResult.Meta):
        verbose_name = "QuantiFERON-TB Gold Plus"
        verbose_name_plural = "QuantiFERON-TB Gold Plus"

    def __str__(self):
        return f"QFT-Plus — {self.sample.code}"

    @staticmethod
    def interpret(nil, tb1, tb2, mitogen):
        cutoff = Decimal("0.35")
        if nil > 8:
            return "IND"
        for tb in (tb1, tb2):
            diff = tb - nil
            if diff >= cutoff and diff >= nil * Decimal("0.25"):
                return "POS"
        if mitogen - nil < Decimal("0.5"):
            return "IND"
        return "NEG"

    def save(self, *args, **kwargs):
        self.interpretation = self.interpret(self.nil, self.tb1, self.tb2, self.mitogen)
        if "update_fields" in kwargs and kwargs["update_fields"] is not None:
            kwargs["update_fields"] = list(kwargs["update_fields"]) + ["interpretation"]
        super().save(*args, **kwargs)

    @property
    def tb1_minus_nil(self):
        return self.tb1 - self.nil

    @property
    def tb2_minus_nil(self):
        return self.tb2 - self.nil

    @property
    def mitogen_minus_nil(self):
        return self.mitogen - self.nil
