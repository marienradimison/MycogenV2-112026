@echo off
rem Sauvegarde quotidienne de la base PostgreSQL (format compresse, restauration avec pg_restore).
rem Le mot de passe est lu dans %APPDATA%\postgresql\pgpass.conf (voir README).
set PGBIN=C:\Program Files\PostgreSQL\18\bin
set DEST=D:\Sauvegardes\Mycogen
if not exist "%DEST%" mkdir "%DEST%"
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set STAMP=%%d
"%PGBIN%\pg_dump.exe" -h localhost -U mycogen -F c -f "%DEST%\mycogen_%STAMP%.dump" mycogen
rem Conservation : 30 jours
forfiles /p "%DEST%" /m *.dump /d -30 /c "cmd /c del @path" 2>nul
