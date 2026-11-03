"""Bibliothèque de codes d'analyse + conversion des analyses demandées vers ces codes."""
from django.db import migrations

CODES = [  # code, signification, famille, méthode, ordre
    ("GNX-RIF", "Genexpert RIF Ultra", "XPERT_ULTRA", "", 10),
    ("GNX-XDR", "Genexpert XDR", "XPERT_XDR", "", 20),
    ("FLUO-AUR", "Microscopie - Fluorescence Auramine", "MICROSCOPY", "FM", 30),
    ("ZN", "Microscopie - Ziehl-Neelsen", "MICROSCOPY", "ZN", 40),
    ("Cult-LJ", "Culture sur LJ", "CULTURE", "LJ", 50),
    ("Cult-MGIT", "Culture sur MGIT", "CULTURE", "MGIT", 60),
    ("DST-LJ", "Antibiogramme sur LJ", "DST", "LJ", 70),
    ("DST-MGIT", "Antibiogramme sur MGIT", "DST", "MGIT", 80),
    ("NPOC", "NPOC Pluslife", "NPOC", "", 90),
    ("QFT", "QuantiFERON-TB Gold Plus", "QFT", "", 100),
    ("WGS", "Whole Genome Sequencing", "WGS", "", 110),
]
OLD = {"XPERT_ULTRA": "GNX-RIF", "XPERT_XDR": "GNX-XDR", "MICROSCOPY": "FLUO-AUR", "CULTURE": "Cult-MGIT",
       "DST": "DST-MGIT", "NPOC": "NPOC", "QFT": "QFT"}


def forwards(apps, schema_editor):
    AnalysisCode = apps.get_model("core", "AnalysisCode")
    for code, meaning, kind, method, order in CODES:
        AnalysisCode.objects.get_or_create(code=code, defaults={
            "meaning": meaning, "kind": kind, "method": method, "order": order})
    Sample = apps.get_model("core", "Sample")
    for s in Sample.objects.exclude(requested_analyses=[]):
        new = [OLD.get(a, a) for a in s.requested_analyses or []]
        if new != s.requested_analyses:
            s.requested_analyses = new
            s.save(update_fields=["requested_analyses"])


class Migration(migrations.Migration):
    dependencies = [("core", "0009_analysiscode")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
