# CCRL_Scripts

Script e risultati per i test in stile CCRL 40/15 (host: 2x Xeon Gold 6138, 2 nodi NUMA,
20 core / 40 thread ciascuno, Windows 11).

```
benchmark/
  ccrl_bench.py                        calibrazione del time control con il bench di Stockfish 10
  results/                             output CSV/JSON delle calibrazioni (uno per host/data)
tournaments/
  <AAAA-MM-GG>_<Motore>_<ver>_4CPU/
    scripts/                           driver del gauntlet e script di avvio/stop/risultati
    config/                            README di configurazione, elenco motori, rating
results/gauntlets/                     risultati dei gauntlet (PGN, tabelle, log)
engines/REPORT.md                      motori usati: versioni, release, asset, SHA256, opzioni UCI
```

## benchmark

`ccrl_bench.py` misura il bench di Stockfish 10 con N istanze in parallelo, pinnate una per CPU,
e calcola il fattore rispetto al riferimento CCRL (i7-4770K, 2054 ms) da cui ricavare il time
control equivalente. Nessuna dipendenza esterna; funziona su Windows e Linux.

```
python benchmark/ccrl_bench.py                 # automatico
python benchmark/ccrl_bench.py --levels 1,20,40
```

## tournaments

Un gauntlet per cartella. Gli script girano in `CCRL\gauntlets\<nome>\` sulla macchina di test:

- `scripts/gauntlet.bat` - tutti i parametri (time control, Threads, Hash, aggiudicazioni,
  Syzygy, numero di partite, affinity) sono in cima al file
- `scripts/start_all.bat` - avvia (o riprende) un'istanza per nodo NUMA
- `scripts/stop_all.bat` - ferma driver, fastchess e motori
- `scripts/run_node.py` - driver di un nodo: sequenza di match a 2 motori, aperture senza
  ripetizioni fra nodi e passate, ripresa dopo interruzione, PGN per partita, Job Object per
  vincolare al nodo NUMA anche i motori che si auto-pinnano
- `scripts/merge_results.bat` - unisce i PGN e calcola la classifica
- `config/README.md` - configurazione completa del gauntlet e procedura di ripresa

I binari dei motori, le reti NNUE e i tablebase non sono versionati (`.gitignore`):
vedi `engines/REPORT.md` per release e checksum.
