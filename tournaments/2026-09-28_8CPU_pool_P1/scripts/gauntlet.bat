@echo off
setlocal
rem =====================================================================
rem  PARAMETRI DEL GAUNTLET - modificare qui
rem =====================================================================
set MODE=gauntlet
rem   gauntlet  = il motore sotto test contro ogni avversario
rem   roundrobin= tutti contro tutti (n*(n-1)/2 accoppiamenti)
set HASH=4096
set THREADS=8
rem Time control fastchess (base+incremento in secondi), da ccrl_bench.py.
set TC=103+1
rem corsie indipendenti per nodo x partite in parallelo dentro una corsia:
rem LANES x THREADS <= core fisici del nodo (20). Aperture per nodo: ROUNDS_PER_PASS (es. "8,7").
rem Piu' corsie = nessun tempo morto a fine match (ogni corsia ha il suo fastchess).
set LANES=2
set CONCURRENCY=1
set PASSES=1
rem Passate da giocare davvero (<= PASSES): permette di ridurre il torneo a
rem meta' senza spostare le aperture gia' assegnate.
set PLAY_PASSES=
set ROUNDS_PER_PASS=8,7
set LOG_LEVEL=info
rem mask di affinity relativa al nodo NUMA (un thread per core fisico), applicata
rem anche come limite di Job Object: deve coincidere con quella in start_node*.bat
set AFFINITY_MASK=0x5555555555
set EVENT=CCRL Blitz 8CPU pool P1
set SITE=Milan
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
rem BG=1 (impostato da gauntlet_bg.bat): driver senza console, sopravvive alla
rem chiusura della finestra e alla disconnessione RDP. Altrimenti gira in primo piano.
if "%BG%"=="1" (
  start "" /B pythonw "%~dp0run_node.py"
  echo [node %NODE%] driver avviato in background.
  exit /b 0
)
python "%~dp0run_node.py"
echo.
echo [node %NODE%] driver terminato con codice %ERRORLEVEL%.
endlocal
