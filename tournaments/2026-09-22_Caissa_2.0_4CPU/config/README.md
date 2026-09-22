# Gauntlet CCRL 40/15 - Caissa 2.0 (4CPU) - configurazione

Creato il 2026-09-22. Cartella: `CCRL\gauntlets\2026-09-22_Caissa_2.0_4CPU\`

## Macchina

- 2x Intel Xeon Gold 6138 (Skylake-SP): 2 nodi NUMA = 2 processor group Windows, 20 core / 40 thread ciascuno.
  Topologia letta con `GetLogicalProcessorInformationEx` (`bench\ccrl_bench.py`): i sibling HT sono adiacenti
  (CPU 2k e 2k+1 = stesso core) -> mask "un thread per core" = `0x5555555555`, identica per i due nodi
  (verificata: `start /NODE n /AFFINITY 0x5555555555` -> gruppo n, 20 CPU).
- RAM 95 GB.
- Windows 11 Pro, Python 3.12, fastchess 1.8.2-alpha (`tools\fastchess\`).

## Condizioni di gioco

| Parametro | Valore | Dove si cambia |
|---|---|---|
| Time control | `1690+19` (1690 s + 19 s/mossa: equivalente CCRL 15m+10s scalato con il fattore del benchmark `bench\ccrl_bench.py` a 40 istanze, ~1.88; incremento intero perche' alcuni motori non gestiscono incrementi decimali) | `scripts\gauntlet.bat` -> `TC` |
| Threads | 4 per motore | `THREADS` |
| Hash | 2048 MB per motore (regola: 512 MB per core -> 4 core = 2048) | `HASH` |
| Ponder | off (fastchess non manda mai `go ponder`; `Ponder=false` ai motori che espongono l'opzione) | - |
| Aperture | `books\avt-book-2026.pgn` (41 092 aperture, 4-16 semimosse, max 8 mosse), ordine sequenziale; ogni apertura giocata 2 volte a colori invertiti (`-games 2 -repeat`) | `BOOK` |
| Partite | 40 per avversario (20 per nodo) -> 760 totali | `PASSES` x `ROUNDS_PER_PASS` x 2 x 2 nodi |
| Aggiudicazioni | **patta**: dalla mossa 35, entrambi i motori entro +-10 cp per 8 mosse consecutive (`-draw movenumber=35 movecount=8 score=10`; il contatore si azzera a ogni cattura/mossa di pedone); **resa**: entrambi i motori con \|score\| >= 600 cp per 4 mosse consecutive (`-resign movecount=4 score=600 twosided=true`) | `EXTRA_ARGS` |
| Tablebase | Syzygy 3-4-5 (WDL+DTZ, 145+145 file, 940 MB) in `tb\syzygy\3-4-5\` dal mirror ufficiale tablebase.lichess.ovh (verificate con Stockfish). **Attive per i motori** che espongono `SyzygyPath` (`SYZYGY_PATH`; non la espongono Alexandria, Hobbes, Quanticade, Tarnished). Aggiudicazione TB di fastchess (`-tb`) NON attiva (riga pronta ma commentata) | `SYZYGY_PATH`, `EXTRA_ARGS` |
| Recovery | `-recover` (fastchess riavvia un motore che crasha e continua) | - |
| Log | `-log level=info engine=true`: un file per match in `logs\`, con tutto il traffico UCI (stimati 1-3 MB/partita) | `LOG_LEVEL` |
| PGN | `pgn\node0.pgn`, `pgn\node1.pgn` (scritti da fastchess: SAN + nodes, nps, seldepth, timeleft). fastchess sa scrivere solo un file per run, quindi il driver estrae ogni 30 s le partite concluse, **una per file**, in `pgn\games\node<N>_<nnnn>_<Bianco>_vs_<Nero>.pgn` | - |
| Modalita' | `gauntlet` (Caissa vs tutti). `roundrobin` = tutti contro tutti (190 accoppiamenti, 7600 partite) | `MODE` |

## Distribuzione sui nodi NUMA

Due istanze indipendenti, una per nodo, ognuna con `-concurrency 5` (5 partite in parallelo x 4 thread
= 20 thread = i 20 core fisici del nodo, dato che con ponder off pensa un solo motore per partita):

- `start_node0.bat`: `start /NODE 0 /AFFINITY 0x5555555555 ...`
- `start_node1.bat`: `start /NODE 1 /AFFINITY 0x5555555555 ...`

In piu' il driver (`run_node.py`) si mette in un **Job Object** con limite di gruppo NUMA + affinity
(`AFFINITY_MASK`), ereditato da fastchess e da tutti i motori. Serve perche' **Caissa 2.0 fa il pinning
dei propri thread da sola su tutti i nodi NUMA** (`src/backend/Search.cpp`, `PinCurrentThreadToNumaNode`)
ignorando l'affinity ereditata: senza Job Object i suoi thread finivano su entrambi i nodi con mask
completa (HT inclusi); con il Job Object restano nel nodo giusto con mask `0x5555555555` (verificato).

## Perche' non `-tournament gauntlet` di fastchess

Dal sorgente di fastchess 1.8.2:

1. `OpeningBook::setup` tronca il libro a `-rounds` aperture: un gauntlet con 10 round userebbe solo 10
   aperture, ripetute contro tutti gli avversari.
2. `-config file=` (ripresa) scarta le statistiche se i motori sono piu' di 2
   (`Warning: Stats will be dropped for more than 2 engines`): non si potrebbe riprendere da dove si era.

Quindi ogni istanza esegue una sequenza di **match a 2 motori** (Caissa vs avversario), in `PASSES`=2
passate da `ROUNDS_PER_PASS`=5 aperture (10 partite) ciascuna. Ordine: passata 1 contro tutti i 19
avversari, poi passata 2: se ci si ferma a meta' i risultati restano bilanciati fra gli avversari.

Aperture: blocchi disgiunti di 5, indice di partenza
`start = 1 + ((nodo*2 + passata-1) * 19 + avversario) * 5`
-> nodo 0 usa le aperture 1-190, nodo 1 le 191-380. Nessuna apertura si ripete (ne' fra nodi, ne' fra
passate, ne' fra avversari). Il tag `Event` del PGN contiene nodo e passata.

## Motori (Threads=4, Hash=2048; dettagli, SHA256 e note in `engines\REPORT.md`)

| Nome nel PGN | Eseguibile | `id name` | Opzioni impostate |
|---|---|---|---|
| Caissa 2.0 | `engines\Caissa_2.0\caissa-2.0-x64-avx2.exe` | `Caissa 2.0 AVX2` | Threads=4, Hash=2048, Ponder=false |
| Stockfish 19 | `engines\Stockfish_19\stockfish\stockfish-windows-x86-64-universal.exe` | `Stockfish 19` | Threads=4, Hash=2048, Ponder=false |
| Reckless 0.9.0 | `engines\Reckless_0.9.0\reckless-windows-avx2.exe` | `Reckless 0.9.0` | Threads=4, Hash=2048 |
| PlentyChess 7.0.0 | `engines\PlentyChess_7.0.0\PlentyChess-7.0.0-windows-avx2.exe` | `PlentyChess 7.0.0` | Threads=4, Hash=2048, Ponder=false |
| pawnocchio 2.0.1 | `engines\pawnocchio_2.0.1\pawnocchio-2.0.1-windows-x86_64_v3.exe` | `pawnocchio 2.0.1` | Threads=4, Hash=2048 |
| Obsidian 16.0 | `engines\Obsidian_16.0\Obsidian160-avx2.exe` | `Obsidian 16.0` | Threads=4, Hash=2048 |
| Cinder 0.6.1 | `engines\Cinder_0.6.1\cinder-v0.6.1-windows-avx2.exe` | `Cinder 0.6.1` | Threads=4, Hash=2048 |
| Alexandria 9.0.0 | `engines\Alexandria_9.0.0\Alexandria-9.0-avx2.exe` | `Alexandria-9.0.0` | Threads=4, Hash=2048 |
| Stormphrax 8.0.0 | `engines\Stormphrax_8.0.0\stormphrax-8.0.0-avx2-bmi2.exe` | `Stormphrax 8.0.0` | Threads=4, Hash=2048 |
| Hobbes 3.0 | `engines\Hobbes_3.0\hobbes-windows-avx2.exe` | `Hobbes 3.0` | Threads=4, Hash=2048 |
| Viridithas 20.0.0 | `engines\Viridithas_20.0.0\viridithas-20-win-x86-64-v3.exe` | `Viridithas 20.0.0` | Threads=4, Hash=2048, Ponder=false |
| Triumviratus 7.0 | `engines\Triumviratus_7.0\Triumviratus_7.0_avx2.exe` | `Triumviratus - 7.0 2026-09-10` | Threads=4, Hash=2048 |
| Coda 0.9.3 | `engines\Coda_0.9.3\coda-0.9.3-windows-x86-64-v3.exe` | `Coda 0.9.3` | Threads=4, Hash=2048, Ponder=false, OwnBook=false |
| Astra 7.0 | `engines\Astra_7.0\astra-7.0-avx2.exe` | `Astra 7.0` | Threads=4, Hash=2048 |
| Berserk 14 | `engines\Berserk_14\berserk-14-avx2.exe` | `Berserk 14` | Threads=4, Hash=2048, Ponder=false |
| Tarnished 6.0-Eternal | `engines\Tarnished_6.0-Eternal\tarnished-6.0-eternal_x86-64-avx2.exe` | `Tarnished v6.0 (Eternal)` | Threads=4, Hash=2048 |
| Halogen 16 | `engines\Halogen_16\Halogen-16.0.0-windows-x86_64-avx2.exe` | `Halogen 16.0.0` | Threads=4, Hash=2048 |
| Quanticade Cronus 3.0 | `engines\Quanticade_Cronus-3.0\Quanticade-Windows-clang-x86-64-bmi2.exe` | `Quanticade Cronus 3.0` | Threads=4, Hash=2048 |
| Clover 9.0 | `engines\Clover_9.0\Clover.9.0-avx2.exe` | `Clover 9.0` | Threads=4, Hash=2048 |
| PZChessBot 7.1 | `engines\PZChessBot_7.1\pzchessbot-win-avx2-pext.exe` | `PZChessBot v7.1` | Threads=4, Hash=2048 |

Note dal REPORT: Stockfish 19 e' un binario *universal* che su questa CPU esegue il codice AVX-512 (non
forzabile ad AVX2); Coda 0.9.3 (build v3) usa a runtime l'inferenza NNUE AVX-512; Stormphrax/Quanticade/
PZChessBot sono build bmi2/pext (nessuna avx2 pura disponibile). Coda: `OwnBook=false` (default true).

## Avvio / stop

```
scripts\start_all.bat          avvia o riprende entrambe le istanze (due finestre "CCRL gauntlet - node 0/1")
scripts\start_node0.bat        solo nodo 0
scripts\start_node1.bat        solo nodo 1
scripts\stop_all.bat           ferma tutto (driver, fastchess, motori); le partite in corso vanno perse
```
NON avviare due volte lo stesso nodo. Le finestre restano aperte a fine gauntlet (`cmd /k`).

## Ripresa dopo interruzione

Rilanciare lo stesso `start_nodeN.bat` (o `start_all.bat`). Il driver, per ogni (passata, avversario):

- conta nel PGN del nodo le partite concluse con quel tag `Event`: se sono gia' 10 -> salta;
- se esiste `logs\nodeN_pK_<match>.json` e ci sono partite -> `fastchess -config file=<json>`: fastchess
  ricarica motori, opzioni, statistiche e riprende dall'apertura successiva (stato salvato a ogni partita,
  `-autosaveinterval 1`); si perdono al massimo le partite in corso al momento dell'interruzione;
- altrimenti avvia il match da zero.

Prima di riprendere assicurarsi che non ci siano `fastchess.exe` o motori rimasti in esecuzione
(`scripts\stop_all.bat`). Per rigiocare un match, cancellarne il `.json` e rimuovere le sue partite dal
PGN (o cambiare `EVENT`). Le modifiche ai parametri in `gauntlet.bat` valgono per i match avviati dopo;
un match ripreso da `.json` usa i parametri con cui era partito.

## Risultati

`scripts\merge_results.bat` -> `results\all_games.pgn`, `results\summary.md`, `results\results.csv`
(tabella per avversario con W/D/L, %, Elo diff +-95%, per colore, durata media, terminazioni, controllo
che ogni coppia abbia 2 partite). Se `config\ratings.csv` contiene i rating CCRL degli avversari
(`name,rating`) calcola anche il performance rating stimato.

## RAM stimata

Per nodo: 5 partite x 2 motori x (2048 MB hash + 100-250 MB di rete/strutture) ~= 22-23 GB.
Totale ~45 GB su 95 GB (fastchess tiene vivi i 10 processi motore per tutta la durata di un match).
Windows alloca la hash solo quando viene toccata, quindi il picco reale si raggiunge dopo qualche partita.

## Durata stimata

Partita media ~60-100 mosse: ~2 x (1690 + 80 x 19) s ~= 1.5-1.8 h senza aggiudicazioni (con le
aggiudicazioni attive le partite decise/patte finiscono prima). 380 partite per nodo / 5 in parallelo
-> ~100-140 ore per nodo (4-6 giorni), i due nodi in parallelo. `results\summary.md` riporta la durata
media reale delle partite giocate.
