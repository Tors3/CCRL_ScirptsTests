@echo off
rem Avvia (o riprende) entrambi i nodi in background, uno per nodo NUMA.
rem Per seguirlo:  scripts\status.bat      Per fermarlo:  scripts\stop_all.bat
start "CCRL gauntlet bg - node 0" /NODE 0 /AFFINITY 0x5555555555 /MIN cmd /c call "%~dp0gauntlet_bg.bat" 0
ping -n 8 127.0.0.1 >nul
start "CCRL gauntlet bg - node 1" /NODE 1 /AFFINITY 0x5555555555 /MIN cmd /c call "%~dp0gauntlet_bg.bat" 1
ping -n 8 127.0.0.1 >nul
powershell -NoProfile -Command "$d=(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_node.py*' }); Write-Host ('driver attivi: ' + $d.Count + ' (attesi 2)'); if ($d.Count -lt 2) { Write-Host 'ATTENZIONE: un nodo non e'' partito, controllare logs\node*_driver.log' }"
pause
