"""Serveur de production intranet (waitress, compatible Windows).

    python manage.py serve                 # 0.0.0.0:8000
    python manage.py serve --port 80

Valeurs par défaut lues dans .env : MYCOGEN_HOST (0.0.0.0) et MYCOGEN_PORT (8000).
Derrière la passerelle Node (MycogenV2-NodeJS) : MYCOGEN_HOST=127.0.0.1 et MYCOGEN_PORT=8001.
"""
import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Lance Mycogen en production sur le réseau local (waitress)."

    def add_arguments(self, parser):
        parser.add_argument("--host", default=os.environ.get("MYCOGEN_HOST", "0.0.0.0"))
        parser.add_argument("--port", type=int, default=int(os.environ.get("MYCOGEN_PORT", "8000")))
        parser.add_argument("--threads", type=int, default=8)

    def handle(self, *args, **opts):
        from waitress import serve

        from mycogen.wsgi import application

        if settings.DEBUG:
            self.stderr.write(self.style.WARNING("DJANGO_DEBUG=True : à désactiver en production (.env)."))
        call_command("collectstatic", interactive=False, verbosity=0)
        self.stdout.write(f"Mycogen disponible sur http://{opts['host']}:{opts['port']}  "
                          f"(hôtes autorisés : {', '.join(settings.ALLOWED_HOSTS)})")
        serve(application, host=opts["host"], port=opts["port"], threads=opts["threads"])
