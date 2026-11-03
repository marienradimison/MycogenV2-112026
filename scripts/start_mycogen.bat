@echo off
rem Demarre Mycogen (serveur web intranet). A lancer au demarrage via le Planificateur de taches.
cd /d "%~dp0.."
".venv\Scripts\python.exe" manage.py serve --port 8000 >> logs\serveur.log 2>&1
