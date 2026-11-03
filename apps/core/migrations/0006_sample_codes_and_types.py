"""Convertit les anciens n° d'échantillon (MYC26-00001) au format CNRM (26-0001)
et les anciens types de prélèvement vers la nouvelle liste."""
import re

from django.db import migrations

OLD_TYPES = {"INDUCED": "SPUTUM", "GASTRIC": "GASTRIC_LAV", "BLOOD": "OTHER", "PAXGENE": "OTHER",
             "QFT": "OTHER", "ISOLATE": "OTHER"}
OLD_TYPE_LABELS = {"INDUCED": "crachat induit", "BLOOD": "sang total", "PAXGENE": "sang PAXgene",
                   "QFT": "tubes QuantiFERON", "ISOLATE": "souche / isolat"}


def forwards(apps, schema_editor):
    Sample = apps.get_model("core", "Sample")
    taken = set(Sample.objects.values_list("code", flat=True))
    for s in Sample.objects.all():
        changed = []
        m = re.fullmatch(r"[A-Z]*(\d{2})-0*(\d+)", s.code or "")
        if m:
            new = f"{m.group(1)}-{int(m.group(2)):04d}"
            if new != s.code and new not in taken:
                taken.discard(s.code)
                taken.add(new)
                s.code = new
                changed.append("code")
        if s.sample_type in OLD_TYPES:
            if s.sample_type in OLD_TYPE_LABELS and not s.type_detail:
                s.type_detail = OLD_TYPE_LABELS[s.sample_type]
                changed.append("type_detail")
            s.sample_type = OLD_TYPES[s.sample_type]
            changed.append("sample_type")
        if changed:
            s.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [("core", "0005_remove_sample_requested_tests_sample_case_and_more")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
