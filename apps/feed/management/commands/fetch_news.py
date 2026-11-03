"""Met à jour les actualités scientifiques de la semaine (3 articles).

    python manage.py fetch_news            # complète la semaine si besoin
    python manage.py fetch_news --force    # renouvelle la sélection

Le tableau de bord le fait aussi automatiquement (au plus toutes les 6 h) ; cette commande
peut être planifiée chaque lundi matin via le Planificateur de tâches.
"""
from django.core.management.base import BaseCommand

from apps.feed import news


class Command(BaseCommand):
    help = "Récupère les actualités scientifiques sur la tuberculose (PubMed, OMS, presse)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        if opts["force"]:
            news.NewsArticle.objects.filter(week=news.week_start()).delete()
        added = news.refresh()
        self.stdout.write(self.style.SUCCESS(f"{added} article(s) ajouté(s)."))
        for a in news.current_articles():
            self.stdout.write(f" • [{a.get_source_display()}] {a.title[:90]} — {a.publisher}")
