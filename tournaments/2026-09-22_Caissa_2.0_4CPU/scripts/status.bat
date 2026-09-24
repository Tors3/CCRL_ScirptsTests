@echo off
rem Stato rapido del gauntlet: processi attivi, partite concluse, ultime righe dei log.
setlocal
set G=%~dp0..
powershell -NoProfile -Command ^
  "$g='%~dp0..'; " ^
  "$drv=(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_node.py*' }).Count; " ^
  "$fc=(Get-Process fastchess -ErrorAction SilentlyContinue).Count; " ^
  "$en=(Get-Process | Where-Object { $_.Path -like 'C:\Users\Francesco\Desktop\CCRL\engines\*' }).Count; " ^
  "$ram=[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,1); " ^
  "$games=(Select-String -Path \"$g\pgn\node*.pgn\" -Pattern '^\[Result \"(1-0|0-1|1/2-1/2)\"\]' -ErrorAction SilentlyContinue).Count; " ^
  "Write-Host \"driver: $drv/2   fastchess: $fc   motori: $en   RAM libera: $ram GB   partite concluse: $games/760\"; " ^
  "Get-ChildItem \"$g\logs\node*_driver.log\" | ForEach-Object { Write-Host ''; Write-Host $_.Name -ForegroundColor Cyan; Get-Content $_.FullName | Where-Object { $_ -notmatch 'CMD:' } | Select-Object -Last 4 }"
endlocal
pause
