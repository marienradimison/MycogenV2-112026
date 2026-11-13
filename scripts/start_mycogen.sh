#!/usr/bin/env bash
# Démarre MYCOGEN (serveur web intranet) sous Linux / WSL. Lancé par systemd (deploy/wsl/mycogen-web.service).
cd "$(dirname "$0")/.." || exit 1
exec .venv/bin/python manage.py serve --port "${MYCOGEN_PORT:-8000}"
