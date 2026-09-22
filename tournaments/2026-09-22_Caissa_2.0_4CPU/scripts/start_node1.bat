@echo off
rem Istanza B: nodo NUMA 1, un thread per core fisico (la mask e' relativa al nodo)
start "CCRL gauntlet - node 1" /NODE 1 /AFFINITY 0x5555555555 cmd /k call "%~dp0gauntlet.bat" 1
