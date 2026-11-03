"""Plan rectifié : crée une salle par emplacement, avec le numéro du plan (1 à 21, 5a, 12b…).

Les anciennes zones (N01…S11) n'existent plus : les salles éventuellement saisies sur ces zones
sont conservées en les rattachant à l'emplacement portant leur numéro s'il existe, sinon supprimées
de la carte (zone vidée impossible : champ unique) — en pratique aucune salle n'était attribuée.
"""
from django.db import migrations

KEYS = ["21", "20", "19", "18", "17", "16b", "16a", "15b", "15a", "14b", "14a", "13c", "13b", "13a",
        "12c", "12b", "12a", "11", "10", "1", "2", "3", "4", "5a", "5b", "6a", "6b", "7", "8", "9"]
USAGE = {"1": "SANIT", "2": "SANIT"}


def forwards(apps, schema_editor):
    Room = apps.get_model("core", "Room")
    for room in Room.objects.exclude(zone__in=KEYS):
        if room.number in KEYS and not Room.objects.filter(zone=room.number).exists():
            room.zone = room.number
            room.save(update_fields=["zone"])
        else:
            room.delete()
    for key in KEYS:
        if not Room.objects.filter(zone=key).exists() and not Room.objects.filter(number=key).exists():
            Room.objects.create(zone=key, number=key, usage=USAGE.get(key, ""))


class Migration(migrations.Migration):
    dependencies = [("core", "0012_room_plan_v2")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
