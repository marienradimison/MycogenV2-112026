"""Efface les identifiants externes générés automatiquement (PT26-00157…) : un identifiant externe non saisi reste vide.

    python manage.py clear_auto_patient_codes            # simulation : liste ce qui serait effacé
    python manage.py clear_auto_patient_codes --apply    # efface réellement (sauvegarder la base avant)
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import ActivityLog, Patient

AUTO_CODE = r"^PT\d{2}-\d{5}$"


class Command(BaseCommand):
    help = "Efface les identifiants externes de patients générés automatiquement (format PTaa-nnnnn)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Effacer réellement (sinon simulation)")

    def handle(self, *args, **opts):
        patients = Patient.objects.filter(code__regex=AUTO_CODE).order_by("code")
        n = patients.count()
        for p in patients[:20]:
            self.stdout.write(f"  {p.code}  {p.full_name}")
        if n > 20:
            self.stdout.write(f"  … et {n - 20} autre(s)")
        if not opts["apply"]:
            self.stdout.write(self.style.WARNING(f"Simulation : {n} identifiant(s) automatique(s) à effacer. "
                                                 "Relancer avec --apply pour les effacer."))
            return
        with transaction.atomic():
            for p in patients:
                ActivityLog.objects.create(action="UPDATE", model=Patient._meta.verbose_name, object_id=p.pk,
                                           object_repr=str(p)[:200],
                                           changes={"identifiant externe": f"{p.code} → (vide, généré automatiquement)"})
            patients.update(code="")
        self.stdout.write(self.style.SUCCESS(f"{n} identifiant(s) automatique(s) effacé(s)."))
