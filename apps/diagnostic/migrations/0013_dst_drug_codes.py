# Antibiogrammes : codes de la bibliothèque pour les fluoroquinolones (LFX → LEV, MFX → MOX)

from django.db import migrations

RENAME = {"LFX": "LEV", "MFX": "MOX"}


def rename(apps, schema_editor, mapping=RENAME):
    DST = apps.get_model("diagnostic", "DST")
    for dst in DST.objects.all():
        results = dst.results or {}
        if any(k in results for k in mapping):
            dst.results = {mapping.get(k, k): v for k, v in results.items()}
            dst.save(update_fields=["results"])


def unrename(apps, schema_editor):
    rename(apps, schema_editor, {v: k for k, v in RENAME.items()})


class Migration(migrations.Migration):

    dependencies = [
        ('diagnostic', '0012_reading_sheet_fields'),
    ]

    operations = [
        migrations.RunPython(rename, unrename),
    ]
