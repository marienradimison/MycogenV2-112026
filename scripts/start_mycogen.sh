#!/usr/bin/env bash
# Démarre MYCOGEN (serveur web intranet) sous Linux / WSL. Lancé par systemd (deploy/wsl/mycogen-web.service).
cd "$(dirname "$0")/.." || exit 1
# Adresse et port : MYCOGEN_HOST / MYCOGEN_PORT dans .env (défaut 0.0.0.0:8000).
exec .venv/bin/python manage.py serve
