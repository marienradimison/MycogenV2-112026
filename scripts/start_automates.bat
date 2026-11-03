@echo off
rem Demarre le service de connexion aux automates (GeneXpert, MGIT, Pluslife).
cd /d "%~dp0.."
".venv\Scripts\python.exe" manage.py instruments_listen >> logs\automates.log 2>&1
