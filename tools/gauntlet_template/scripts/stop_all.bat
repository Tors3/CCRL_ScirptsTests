@echo off
rem Ferma il gauntlet: driver python, fastchess e tutti i motori (le partite in corso
rem vanno perse, quelle concluse restano nei PGN; rilanciare start_all.bat per riprendere).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_node.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
taskkill /F /IM fastchess.exe >nul 2>&1
powershell -NoProfile -Command "Get-Process | Where-Object { $_.Path -like 'C:\Users\Francesco\Desktop\CCRL\engines\*' } | Stop-Process -Force -ErrorAction SilentlyContinue"
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "$n = (Get-Process | Where-Object { $_.Path -like 'C:\Users\Francesco\Desktop\CCRL\*' }).Count; if ($n) { Write-Host \"ATTENZIONE: $n processi ancora attivi\" } else { Write-Host 'Gauntlet fermato: nessun processo residuo.' }"
pause
