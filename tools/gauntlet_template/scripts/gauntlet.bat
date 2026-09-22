@echo off
setlocal
rem =====================================================================
rem  PARAMETRI DEL GAUNTLET - modificare qui
rem =====================================================================
set MODE=gauntlet
rem   gauntlet  = Caissa contro ogni avversario (19 accoppiamenti, 760 partite)
rem   roundrobin= tutti contro tutti (190 accoppiamenti, 7600 partite!)
set HASH=2048
set THREADS=4
set TC=1690+19
set CONCURRENCY=5
set PASSES=2
set ROUNDS_PER_PASS=5
set LOG_LEVEL=info
rem mask di affinity relativa al nodo NUMA (un thread per core fisico), applicata
rem anche come limite di Job Object: deve coincidere con quella in start_node*.bat
set AFFINITY_MASK=0x5555555555
set EVENT=CCRL 40/15 gauntlet Caissa 2.0 4CPU
set SITE=Xeon-Server
rem --- Aggiudicazioni fastchess (ATTIVE): patta se dalla mossa 35 entrambi i motori restano entro +-10 cp
rem     per 8 mosse consecutive; resa se entrambi concordano su |score| >= 600 cp per 4 mosse consecutive.
set EXTRA_ARGS=-draw movenumber=35 movecount=8 score=10 -resign movecount=4 score=600 twosided=true
rem --- Aggiudicazione via tablebase di fastchess (NON attiva): decommentare per attivarla
rem set EXTRA_ARGS=%EXTRA_ARGS% -tb C:\Users\Francesco\Desktop\CCRL\tb\syzygy\3-4-5 -tbpieces 5 -tbadjudicate BOTH
rem --- Syzygy 3-4-5 ai motori che espongono SyzygyPath (condizione CCRL 40/15); vuoto = disattivato ---
set SYZYGY_PATH=C:\Users\Francesco\Desktop\CCRL\tb\syzygy\3-4-5
rem --- Sottoinsieme di avversari, es. "1-10" o "3,7" (vuoto = tutti) ---
rem set OPP_FILTER=
rem =====================================================================
rem  Uso: gauntlet.bat <node>   (chiamato da start_node0/1.bat, che impostano
rem       nodo NUMA e affinity con "start /NODE n /AFFINITY mask")
rem  Se il gauntlet si interrompe basta rilanciare lo stesso .bat: il driver
rem  salta i match completi e riprende quelli parziali dal loro .json.
rem =====================================================================
set NODE=%~1
if "%NODE%"=="" set NODE=0
if not defined GAUNTLET_DIR set GAUNTLET_DIR=%~dp0..
cd /d "%GAUNTLET_DIR%"
python "%~dp0run_node.py"
echo.
echo [node %NODE%] driver terminato con codice %ERRORLEVEL%.
endlocal
