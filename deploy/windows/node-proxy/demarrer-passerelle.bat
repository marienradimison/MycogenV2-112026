@echo off
title MYCOGEN V2 - Passerelle
cd /d "%~dp0"

rem Demarrer et maintenir Ubuntu WSL actif
start "MYCOGEN WSL" /min wsl.exe -d Ubuntu-24.04 --exec /bin/sleep infinity

rem Attendre que Django reponde
:attendre
curl.exe -s -o NUL --max-time 5 http://127.0.0.1:8001/
if errorlevel 1 (
    timeout /t 5 /nobreak >nul
    goto attendre
)

rem Lancer la passerelle Node.js
:boucle
node passerelle.js
timeout /t 10 /nobreak >nul
goto attendre
