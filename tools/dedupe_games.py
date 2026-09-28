#!/usr/bin/env python3
r"""
dedupe_games.py - rimuove dai PGN di un gauntlet le partite giocate due volte.

Se il torneo viene interrotto di colpo, puo' capitare che fastchess abbia gia'
scritto una partita nel PGN ma non ancora aggiornato il proprio file di stato
(.json): alla ripresa la stessa partita (stesso round, stessi colori, stessa
apertura) viene rigiocata. Il doppione altera il bilanciamento dei colori e
pesa due volte la stessa apertura, quindi va tolto.

Una partita e' identificata da (Event, White, Black, Round): dentro un match
ogni round ha esattamente due partite, una per colore. Dei doppioni si tiene
quella terminata per prima (GameEndTime), le altre vengono rimosse.
I PGN modificati vengono salvati come .bak prima della riscrittura, e pgn\games\
viene rigenerata.

Uso (dalla cartella CCRL, a torneo fermo):
  python tools\dedupe_games.py --gauntlet-dir gauntlets\<nome> [--dry-run]
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

CCRL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def blocks(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    for b in re.split(r"\n\s*\n(?=\[)", text):
        b = b.strip("\n")
        if b.startswith("["):
            yield b, dict(re.findall(r'^\[(\w+) "(.*)"\]', b, re.M))


def main():
    ap = argparse.ArgumentParser(description="Rimuove le partite doppie da un gauntlet",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--gauntlet-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    gdir = a.gauntlet_dir if os.path.isabs(a.gauntlet_dir) else os.path.join(CCRL_ROOT, a.gauntlet_dir)
    pgns = sorted(glob.glob(os.path.join(gdir, "pgn", "*.pgn")))
    if not pgns:
        sys.exit(f"ERRORE: nessun PGN in {gdir}\\pgn")

    running = [l for l in subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower().splitlines()
               if "fastchess" in l or "pythonw" in l]
    if running and not a.dry_run:
        sys.exit("ERRORE: il gauntlet e' in esecuzione: fermarlo prima (scripts\\stop_all.bat).")

    # prima occorrenza (per GameEndTime) di ogni partita conclusa
    keep = {}
    for p in pgns:
        for _, h in blocks(p):
            if h.get("Result") not in ("1-0", "0-1", "1/2-1/2"):
                continue
            key = (h.get("Event"), h.get("White"), h.get("Black"), h.get("Round"))
            end = h.get("GameEndTime", "")
            if key not in keep or end < keep[key]:
                keep[key] = end

    removed = []
    for p in pgns:
        out, changed = [], False
        for b, h in blocks(p):
            key = (h.get("Event"), h.get("White"), h.get("Black"), h.get("Round"))
            if h.get("Result") in ("1-0", "0-1", "1/2-1/2") and keep.get(key) != h.get("GameEndTime", ""):
                removed.append((os.path.basename(p), h.get("White"), h.get("Black"), h.get("Round"),
                                h.get("Result"), h.get("GameEndTime", "")[:19]))
                changed = True
                continue
            if keep.get(key) == h.get("GameEndTime", ""):
                keep[key] = None          # la prima copia e' stata tenuta: le altre sono doppioni
            out.append(b)
        if changed and not a.dry_run:
            if not os.path.exists(p + ".bak"):
                shutil.copy2(p, p + ".bak")
            open(p, "w", encoding="utf-8").write("".join(b + "\n\n" for b in out))

    for r in removed:
        print(f"  doppione rimosso: {r[1]} vs {r[2]} round {r[3]} {r[4]}  ({r[0]}, finita {r[5]})")
    print(f"\npartite doppie rimosse: {len(removed)}" + ("   [dry-run]" if a.dry_run else ""))

    games_dir = os.path.join(gdir, "pgn", "games")
    if removed and not a.dry_run and os.path.isdir(games_dir):
        shutil.rmtree(games_dir)
        sys.path.insert(0, os.path.join(gdir, "scripts"))
        os.environ["GAUNTLET_DIR"] = gdir
        for node in sorted({m.group(1) for p in pgns for m in [re.search(r"node(\d+)", os.path.basename(p))] if m}):
            os.environ["NODE"] = node
            sys.modules.pop("run_node", None)
            import run_node
            run_node.split_all_pgns()
        print(f"pgn\\games\\ rigenerata: {len(os.listdir(games_dir))} file")


if __name__ == "__main__":
    main()
