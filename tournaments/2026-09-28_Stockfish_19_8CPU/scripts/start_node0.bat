@echo off
rem Istanza A: nodo NUMA 0, un thread per core fisico (sibling HT adiacenti -> bit pari)
rem Mask verificata con GetLogicalProcessorInformationEx il 2026-09-22 (20 core, 40 thread per nodo).
start "CCRL gauntlet - node 0" /NODE 0 /AFFINITY 0x5555555555 cmd /k call "%~dp0gauntlet.bat" 0
