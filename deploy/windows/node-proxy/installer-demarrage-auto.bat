@echo off
rem Ajoute MYCOGEN V2 au dossier "Demarrage" de l'utilisateur Windows courant
rem (lance a l'ouverture de session ; aucun droit administrateur necessaire).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup') + '\MYCOGEN V2 - Passerelle.lnk');" ^
  "$s.TargetPath = '%~dp0demarrer-passerelle.bat'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 7;" ^
  "$s.Description = 'MYCOGEN V2 - passerelle reseau'; $s.Save()"
if errorlevel 1 (
  echo [ERREUR] Raccourci non cree.
) else (
  echo Raccourci "MYCOGEN V2" cree dans le dossier Demarrage.
  echo MYCOGEN V2 demarrera a chaque ouverture de session de ce compte Windows.
)
pause
