# CCRL_Scripts

Script e risultati per i test in stile CCRL 40/15 (host: 2x Xeon Gold 6138, Windows 11).

```
benchmark/            calibrazione del time control con lo Stockfish 10 bench
  ccrl_bench.py       script (Windows/Linux, nessuna dipendenza)
  results/            output CSV/JSON delle calibrazioni (uno per host/data)
tournaments/          script e configurazioni dei tornei/gauntlet (cutechess, ecc.)
results/gauntlets/    risultati dei gauntlet (PGN, tabelle, log)
engines/REPORT.md     elenco motori, versioni, asset, SHA256, opzioni UCI e note
```

I binari dei motori non sono versionati (`.gitignore`): vedi `engines/REPORT.md` per release e checksum.
