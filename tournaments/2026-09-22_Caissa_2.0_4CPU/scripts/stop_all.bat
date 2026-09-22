@echo off
rem Ferma il gauntlet: driver python, fastchess e tutti i motori (le partite in corso vanno perse,
rem quelle concluse restano nei PGN; rilanciare start_all.bat per riprendere).
taskkill /F /FI "WINDOWTITLE eq CCRL gauntlet*" >nul 2>&1
taskkill /F /IM fastchess.exe >nul 2>&1
powershell -NoProfile -Command "Get-Process | Where-Object { $_.Path -like 'C:\Users\Francesco\Desktop\CCRL\engines\*' } | Stop-Process -Force"
echo Gauntlet fermato.
pause
