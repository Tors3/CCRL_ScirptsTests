@echo off
rem Avvia (o riprende) entrambe le istanze, una per nodo NUMA.
call "%~dp0start_node0.bat"
ping -n 6 127.0.0.1 >nul
call "%~dp0start_node1.bat"
