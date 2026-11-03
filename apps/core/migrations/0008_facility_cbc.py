from django.db import migrations


def add_cbc(apps, schema_editor):
    Facility = apps.get_model("core", "Facility")
    Facility.objects.update_or_create(code="CBC", defaults={
        "name": "Centre de Biologie Clinique - IPM", "type": "CBC", "region": "ANALAMANGA",
        "district": "Antananarivo", "active": True, "notes": "Institut Pasteur de Madagascar"})


class Migration(migrations.Migration):
    dependencies = [("core", "0007_alter_facility_type")]
    operations = [migrations.RunPython(add_cbc, migrations.RunPython.noop)]
