@echo off
rem ============================================================================
rem  MYCOGEN V2 - demarrage complet (sans droits administrateur)
rem   1. reveille Ubuntu (WSL) et le garde allume : PostgreSQL et MYCOGEN y
rem      demarrent tout seuls (services systemd) ;
rem   2. lance la passerelle Node qui publie MYCOGEN sur le reseau.
rem  Nom de la distribution : voir "wsl -l -v" (a adapter ci-dessous).
rem ============================================================================
set DISTRO=Ubuntu-24.04
set WSL_UTF8=1
cd /d "%~dp0"

wsl.exe -l -q | findstr /i /c:"%DISTRO%" >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] Distribution WSL "%DISTRO%" introuvable. Modifier DISTRO dans demarrer.bat
  echo          ^(liste : wsl -l -v^).
  pause
  exit /b 1
)

rem Garde Ubuntu allume tant que la session Windows est ouverte.
start "MYCOGEN - WSL" /min wsl.exe -d %DISTRO% --exec /bin/sleep infinity

rem Laisse le temps a PostgreSQL et MYCOGEN de demarrer (la passerelle affiche
rem de toute facon une page "indisponible" tant que MYCOGEN ne repond pas).
timeout /t 5 /nobreak >nul

title MYCOGEN V2 - passerelle reseau (ne pas fermer)
:boucle
node passerelle.js
echo.
echo La passerelle s'est arretee. Redemarrage dans 10 secondes (Ctrl+C pour quitter)...
timeout /t 10 /nobreak >nul
goto boucle
