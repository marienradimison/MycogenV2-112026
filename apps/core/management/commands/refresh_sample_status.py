from django.core.management.base import BaseCommand

from apps.core.models import Sample
from apps.core.status import refresh_status


class Command(BaseCommand):
    help = "Recalcule le statut automatique de tous les echantillons."

    def handle(self, *args, **opts):
        changed = 0
        for sample in Sample.objects.all().iterator():
            old = sample.status
            if refresh_status(sample) != old:
                changed += 1
        self.stdout.write(self.style.SUCCESS(f"{changed} statut(s) mis a jour."))
