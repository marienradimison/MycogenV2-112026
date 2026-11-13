#!/usr/bin/env bash
# Démarre le service de connexion aux automates (GeneXpert, MGIT, Pluslife) sous Linux / WSL.
cd "$(dirname "$0")/.." || exit 1
exec .venv/bin/python manage.py instruments_listen
