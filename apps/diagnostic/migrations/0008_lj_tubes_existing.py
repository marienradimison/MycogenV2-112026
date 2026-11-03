from django.db import migrations


def forwards(apps, schema_editor):
    Culture = apps.get_model("diagnostic", "Culture")
    CultureTube = apps.get_model("diagnostic", "CultureTube")
    for c in Culture.objects.filter(medium="LJ"):
        if not CultureTube.objects.filter(culture=c).exists():
            status = "INCUB" if c.result == "PENDING" else "EXITED"
            CultureTube.objects.bulk_create([CultureTube(culture=c, number=n, status=status,
                                                         status_date=c.result_date) for n in (1, 2)])


class Migration(migrations.Migration):
    dependencies = [("diagnostic", "0007_lj_incubator")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
