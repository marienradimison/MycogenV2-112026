"""Recalcule le délai de positivité de toutes les cultures à partir des dates.

Cultures positives sans date de résultat mais avec un délai saisi (données de démonstration) :
la date de résultat est reconstituée (ensemencement + délai) pour que le calcul reste cohérent.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import migrations


def forwards(apps, schema_editor):
    Culture = apps.get_model("diagnostic", "Culture")
    for c in Culture.objects.all():
        if c.result == "POSITIVE" and not c.result_date and c.ttp_days is not None and c.inoculated_on:
            c.result_date = c.inoculated_on + timedelta(days=int(c.ttp_days))
        ttp = None
        if c.result == "POSITIVE" and c.result_date and c.inoculated_on:
            days = (c.result_date - c.inoculated_on).days
            ttp = Decimal(days) if days >= 0 else None
        c.ttp_days = ttp
        c.save(update_fields=["result_date", "ttp_days"])


class Migration(migrations.Migration):
    dependencies = [("diagnostic", "0005_culture_ttp_computed")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
