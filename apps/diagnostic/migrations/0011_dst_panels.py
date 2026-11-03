"""Antibiogramme par groupe : regroupe les anciennes lignes (1 antibiotique = 1 ligne) en un test par groupe."""
from django.db import migrations, models

FIRST = ["STR", "INH", "RIF", "EMB", "PZA"]
OLD_RESULT = {"S": "S", "R": "R", "I": "I", "CONT": "I"}


def group_rows(apps, schema_editor):
    DST = apps.get_model("diagnostic", "DST")
    groups = {}
    for d in DST.objects.order_by("pk"):
        panel = "FIRST" if d.drug in FIRST else "SECOND"
        groups.setdefault((d.sample_id, d.method, panel), []).append((d, panel))
    for rows in groups.values():
        keep, panel = rows[0]
        keep.panel = panel
        keep.results = {d.drug: OLD_RESULT.get(d.result, "I") for d, _ in rows}
        notes = [f"{d.drug} : CMI {d.mic}" for d, _ in rows if d.mic] + [d.comment for d, _ in rows[1:] if d.comment]
        if notes:
            keep.comment = "\n".join([keep.comment] + notes if keep.comment else notes)
        if any(d.result_status != "VALIDATED" for d, _ in rows):
            keep.result_status = "DRAFT"
        keep.save()
        DST.objects.filter(pk__in=[d.pk for d, _ in rows[1:]]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('diagnostic', '0010_result_codes'),
    ]

    operations = [
        migrations.AddField(
            model_name='dst',
            name='panel',
            field=models.CharField(choices=[('FIRST', 'Première ligne (SIRE + PZA)'), ('SECOND', 'Seconde ligne')], default='FIRST', max_length=6, verbose_name='groupe'),
        ),
        migrations.AddField(
            model_name='dst',
            name='results',
            field=models.JSONField(blank=True, default=dict, verbose_name='résultats par antibiotique'),
        ),
        migrations.RunPython(group_rows, migrations.RunPython.noop),
        migrations.RemoveField(model_name='dst', name='concentration'),
        migrations.RemoveField(model_name='dst', name='drug'),
        migrations.RemoveField(model_name='dst', name='mic'),
        migrations.RemoveField(model_name='dst', name='result'),
    ]
