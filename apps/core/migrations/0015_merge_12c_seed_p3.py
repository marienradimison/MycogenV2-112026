"""Salle 12c fusionnée dans la 12b ; création des salles du laboratoire P3 (RDC) et de l'emplacement autoclave."""
from django.db import migrations

P3 = [("P3-01", "", "BSL3"), ("P3-02", "", "BSL3"), ("P3-03", "", "BSL3"), ("P3-04", "", "BSL3"),
      ("P3-05", "", "BSL3"), ("P3-06", "", "BSL3"), ("P3-07", "", "BSL3"), ("P3-A", "Autoclave", "TECH")]


def forwards(apps, schema_editor):
    Room = apps.get_model("core", "Room")
    old = Room.objects.filter(zone="12c").first()
    target = Room.objects.filter(zone="12b").first()
    if old and target:
        # tout ce qui était rattaché à la 12c rejoint la 12b
        for app_label, model, field in (("quality", "Equipment", "room"), ("quality", "RoomAccess", "room"),
                                        ("instruments", "Instrument", "room"), ("biobank", "StorageUnit", "room")):
            try:
                apps.get_model(app_label, model).objects.filter(**{field: old}).update(**{field: target})
            except LookupError:
                pass
        notes = [n for n in (target.notes, old.notes, f"Fusion avec l'ancienne salle {old.number}.") if n]
        target.notes = "\n".join(notes)
        target.save(update_fields=["notes"])
        old.delete()
    elif old:
        old.zone = "12b"
        old.save(update_fields=["zone"])
    for key, name, usage in P3:
        if not Room.objects.filter(zone=key).exists() and not Room.objects.filter(number=key).exists():
            Room.objects.create(zone=key, number=key, name=name, usage=usage)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_room_zones_p3"),
        ("quality", "0001_initial"),
        ("instruments", "0002_instrument_room_alter_instrument_location"),
        ("biobank", "0003_storageunit_room_alter_storageunit_location"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
