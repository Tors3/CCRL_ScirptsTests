#!/usr/bin/env python3
r"""
rename_engine.py - cambia il nome con cui un motore compare nel gauntlet.

Il nome del giocatore (tag White/Black dei PGN) e' l'etichetta scelta
dall'operatore, non l'identificazione del motore: si cambia per seguire le
convenzioni di una lista (es. "Triumviratus 7.0" -> "Triumviratus 7.0 64-bit").
I tag EngineWhiteName/EngineBlackName, che riportano l'`id name` dichiarato dal
motore stesso, NON vengono toccati.

Il nome compare in quattro posti, che devono restare coerenti fra loro perche'
la ripresa dei match funzioni:

  config\engines.json    nome usato per le partite future
  logs\*.json            stato fastchess dei match in corso (motori + statistiche)
  pgn\*.pgn              tag White/Black delle partite gia' giocate
  pgn\games\*.pgn        copie per singola partita (rigenerate)

Il gauntlet deve essere fermo: lo script si rifiuta di scrivere se trova i
driver in esecuzione (usare scripts\stop_all.bat). I file modificati vengono
salvati con estensione .bak prima della riscrittura.

Uso (dalla cartella CCRL):
  python tools\rename_engine.py --gauntlet-dir gauntlets\<nome> \
      --from "Triumviratus 7.0" --to "Triumviratus 7.0 64-bit" [--dry-run]
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

CCRL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def backup(path):
    if not os.path.exists(path + ".bak"):
        shutil.copy2(path, path + ".bak")


def rename_in_json(path, old, new, dry):
    """Sostituisce il nome in engines[].name e nelle chiavi delle statistiche."""
    d = json.load(open(path, encoding="utf-8"))
    hits = 0

    def walk(obj):
        nonlocal hits
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                nk = k.replace(old, new) if isinstance(k, str) and old in k else k
                if nk != k:
                    hits += 1
                out[nk] = walk(v)
            return out
        if isinstance(obj, list):
            return [walk(x) for x in obj]
        if isinstance(obj, str) and obj == old:
            hits += 1
            return new
        return obj

    d2 = walk(d)
    if hits and not dry:
        backup(path)
        json.dump(d2, open(path, "w", encoding="utf-8"), indent=4, ensure_ascii=False)
    return hits


def rename_in_pgn(path, old, new, dry):
    """Solo i tag White/Black: EngineWhiteName/EngineBlackName restano invariati."""
    text = open(path, encoding="utf-8", errors="replace").read()
    pat = re.compile(r'^\[(White|Black) "' + re.escape(old) + r'"\]$', re.M)
    n = len(pat.findall(text))
    if n and not dry:
        backup(path)
        open(path, "w", encoding="utf-8").write(pat.sub(lambda m: f'[{m.group(1)} "{new}"]', text))
    return n


def main():
    ap = argparse.ArgumentParser(description="Rinomina un motore in un gauntlet",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--gauntlet-dir", required=True)
    ap.add_argument("--from", dest="old", required=True, help="nome attuale")
    ap.add_argument("--to", dest="new", required=True, help="nome nuovo")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    gdir = a.gauntlet_dir if os.path.isabs(a.gauntlet_dir) else os.path.join(CCRL_ROOT, a.gauntlet_dir)
    if not os.path.isdir(gdir):
        sys.exit(f"ERRORE: cartella non trovata: {gdir}")

    running = [p for p in subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower().splitlines()
               if "pythonw" in p or "fastchess" in p]
    if running and not a.dry_run:
        sys.exit("ERRORE: il gauntlet e' in esecuzione (pythonw/fastchess attivi).\n"
                 "        Fermarlo con scripts\\stop_all.bat, poi rilanciare questo script.")

    print(f"'{a.old}' -> '{a.new}'\n")
    tot_pgn = tot_json = 0

    cfg = os.path.join(gdir, "config", "engines.json")
    if os.path.exists(cfg):
        n = rename_in_json(cfg, a.old, a.new, a.dry_run)
        tot_json += n
        print(f"  config\\engines.json: {n} occorrenze")

    for f in sorted(glob.glob(os.path.join(gdir, "logs", "*.json"))):
        n = rename_in_json(f, a.old, a.new, a.dry_run)
        if n:
            tot_json += n
            print(f"  logs\\{os.path.basename(f)}: {n} occorrenze")

    for f in sorted(glob.glob(os.path.join(gdir, "pgn", "*.pgn"))):
        n = rename_in_pgn(f, a.old, a.new, a.dry_run)
        if n:
            tot_pgn += n
            print(f"  pgn\\{os.path.basename(f)}: {n} tag White/Black")

    games_dir = os.path.join(gdir, "pgn", "games")
    if os.path.isdir(games_dir) and not a.dry_run:
        shutil.rmtree(games_dir)
        sys.path.insert(0, os.path.join(gdir, "scripts"))
        os.environ["GAUNTLET_DIR"] = gdir
        nodes = sorted({m.group(1) for f in glob.glob(os.path.join(gdir, "pgn", "node*.pgn"))
                        for m in [re.search(r"node(\d+)", os.path.basename(f))] if m})
        for node in nodes:
            os.environ["NODE"] = node
            sys.modules.pop("run_node", None)
            import run_node
            run_node.split_all_pgns()
        print(f"  pgn\\games\\: rigenerati {len(os.listdir(games_dir))} file")

    print(f"\ntotale: {tot_pgn} tag nei PGN, {tot_json} occorrenze nei JSON"
          + ("   [dry-run, niente scritto]" if a.dry_run else ""))
    if not a.dry_run:
        print("Ricordarsi di rilanciare il gauntlet (schtasks /run /tn \"CCRL Gauntlet\").")


if __name__ == "__main__":
    main()
