@echo off
rem Avvia il driver del nodo indicato SENZA console (pythonw): il gauntlet continua
rem anche se si chiude la finestra o cade la sessione RDP.
rem Tutti i parametri restano quelli di gauntlet.bat: qui si imposta solo BG=1.
setlocal
set BG=1
call "%~dp0gauntlet.bat" %*
endlocal
