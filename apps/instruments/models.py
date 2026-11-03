import hashlib

from django.db import models
from django.urls import reverse

from apps.core.models import LimsModel


class Instrument(LimsModel):
    url_base = "instruments:instrument"

    KINDS = [("GENEXPERT", "GeneXpert (Cepheid)"), ("MGIT", "BD BACTEC MGIT 960 / EpiCenter"),
             ("PLUSLIFE", "Pluslife MiniDock (NPOC)")]
    CONNECTIONS = [
        ("TCP_SERVER", "TCP — le LIMS écoute, l'automate se connecte"),
        ("TCP_CLIENT", "TCP — le LIMS se connecte à l'automate"),
        ("SERIAL", "Port série RS-232"),
        ("FOLDER", "Dossier d'export (fichiers)"),
    ]

    name = models.CharField("nom", max_length=100, unique=True)
    kind = models.CharField("type d'automate", max_length=10, choices=KINDS)
    serial_number = models.CharField("n° de série", max_length=60, blank=True)
    room = models.ForeignKey("core.Room", verbose_name="salle", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="instruments")
    location = models.CharField("précision d'emplacement", max_length=100, blank=True)
    connection = models.CharField("connexion", max_length=10, choices=CONNECTIONS, default="TCP_SERVER")
    host = models.CharField("adresse IP de l'automate", max_length=100, blank=True,
                            help_text="Mode « LIMS se connecte » uniquement")
    port = models.PositiveIntegerField("port TCP", null=True, blank=True,
                                       help_text="Ex. 12000 — doit correspondre à la configuration LIS de l'automate")
    serial_port = models.CharField("port série", max_length=30, blank=True, help_text="Ex. COM3")
    baudrate = models.PositiveIntegerField("vitesse (bauds)", default=9600)
    folder = models.CharField("dossier surveillé", max_length=500, blank=True,
                              help_text="Mode dossier : chemin où le logiciel dépose ses exports")
    reply_to_queries = models.BooleanField(
        "répondre aux requêtes hôte", default=True,
        help_text="Répond « aucune demande » aux requêtes (Q) pour que l'automate ne reste pas en attente")
    active = models.BooleanField("actif", default=True)
    last_seen = models.DateTimeField("dernière communication", null=True, blank=True, editable=False)
    notes = models.TextField("remarques", blank=True)

    class Meta:
        verbose_name = "automate"
        verbose_name_plural = "automates"
        ordering = ["kind", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"


class InstrumentMessage(models.Model):
    """Message brut reçu d'un automate — rien n'est perdu, même s'il n'est pas interprété."""

    KINDS = [("RESULT", "Résultat"), ("QUERY", "Requête (test démarré)"), ("OTHER", "Autre")]
    STATUS = [
        ("NEW", "Non interprété"),
        ("IMPORTED", "Importé"),
        ("INFO", "Information"),
        ("UNMATCHED", "Échantillon inconnu"),
        ("ERROR", "Erreur"),
        ("IGNORED", "Ignoré"),
        ("DUPLICATE", "Doublon"),
    ]

    url_base = "instruments:message"

    instrument = models.ForeignKey(Instrument, verbose_name="automate", on_delete=models.PROTECT,
                                   related_name="messages")
    received_at = models.DateTimeField("reçu le", auto_now_add=True)
    kind = models.CharField("type", max_length=6, choices=KINDS, default="OTHER")
    status = models.CharField("statut", max_length=10, choices=STATUS, default="NEW")
    sample_ref = models.CharField("ID échantillon (automate)", max_length=80, blank=True, db_index=True)
    sample = models.ForeignKey("core.Sample", verbose_name="échantillon", on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="instrument_messages")
    summary = models.CharField("résumé", max_length=255, blank=True)
    detail = models.TextField("détail / erreur", blank=True)
    raw = models.TextField("message brut")
    raw_hash = models.CharField(max_length=64, db_index=True, editable=False)
    result_model = models.CharField(max_length=60, blank=True, editable=False)
    result_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "message d'automate"
        verbose_name_plural = "messages d'automates"
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.instrument.name} · {self.get_kind_display()} · {self.sample_ref or '?'}"

    def save(self, *args, **kwargs):
        if not self.raw_hash:
            self.raw_hash = hashlib.sha256(self.raw.encode("utf-8", "replace")).hexdigest()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("instruments:message_detail", args=[self.pk])

    @property
    def result(self):
        if not (self.result_model and self.result_id):
            return None
        from django.apps import apps
        try:
            return apps.get_model(self.result_model).objects.filter(pk=self.result_id).first()
        except LookupError:
            return None
