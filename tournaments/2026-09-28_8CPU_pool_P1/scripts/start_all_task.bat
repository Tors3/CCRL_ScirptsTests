@echo off
rem Avvio usato dall'attivita' pianificata "CCRL Gauntlet": come start_all_background.bat
rem ma senza pause, cosi' il cmd esce subito e restano solo i due driver pythonw.
rem Lanciato dall'Utilita' di pianificazione, il gauntlet NON dipende da nessuna finestra,
rem shell o applicazione: sopravvive a chiusure, disconnessioni RDP e aggiornamenti di app.
start "CCRL gauntlet - node 0" /NODE 0 /AFFINITY 0x5555555555 /MIN cmd /c call "%~dp0gauntlet_bg.bat" 0
ping -n 8 127.0.0.1 >nul
start "CCRL gauntlet - node 1" /NODE 1 /AFFINITY 0x5555555555 /MIN cmd /c call "%~dp0gauntlet_bg.bat" 1
