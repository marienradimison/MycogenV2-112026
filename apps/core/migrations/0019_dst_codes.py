"""Bibliothèque : antibiotiques de l'antibiogramme par groupe et résultats I / NF / NA."""
from django.db import migrations

CODES = [  # code, signification, catégorie, s'applique à
    ("STR", "Streptomycine", "DRUG", "Antibiogramme — 1re ligne"),
    ("EMB", "Éthambutol", "DRUG", "Antibiogramme — 1re ligne"),
    ("PZA", "Pyrazinamide", "DRUG", "Antibiogramme — 1re ligne"),
    ("LFX", "Lévofloxacine", "DRUG", "Antibiogramme — 2e ligne"),
    ("MFX", "Moxifloxacine", "DRUG", "Antibiogramme — 2e ligne"),
    ("BDQ", "Bédaquiline", "DRUG", "Antibiogramme — 2e ligne"),
    ("LZD", "Linézolide", "DRUG", "Antibiogramme — 2e ligne"),
    ("CFZ", "Clofazimine", "DRUG", "Antibiogramme — 2e ligne"),
    ("DLM", "Délamanide", "DRUG", "Antibiogramme — 2e ligne"),
    ("PMD", "Prétomanide", "DRUG", "Antibiogramme — 2e ligne"),
    ("ETO", "Éthionamide", "DRUG", "Antibiogramme — 2e ligne"),
    ("INH_H", "Isoniazide (haute concentration)", "DRUG", "Antibiogramme — 2e ligne"),
    ("I", "Indéterminé", "SUSCEPT", ""),
    ("NF", "Non fait", "SUSCEPT", ""),
    ("NA", "Non applicable", "SUSCEPT", ""),
]


def seed(apps, schema_editor):
    AnalysisCode = apps.get_model("core", "AnalysisCode")
    for order, (code, meaning, category, scope) in enumerate(CODES, start=1):
        AnalysisCode.objects.get_or_create(code=code, defaults={
            "meaning": meaning, "category": category, "scope": scope, "order": 330 + order,
            "requestable": False})


class Migration(migrations.Migration):
    dependencies = [("core", "0018_result_codes")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
