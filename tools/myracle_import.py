#!/usr/bin/env python3
r"""
myracle_import.py - registra i motori di CCRL\engines\ nella GUI Myracle.

Myracle tiene la lista dei motori in <myracle>\config\engines.json.gz (JSON
compresso con gzip): copiare gli eseguibili in engines\ non basta, serve una
voce in quel file. Questo script la genera leggendo, per ogni motore,
l'eseguibile e il file uci_options.txt prodotto dalla verifica UCI, e la
fonde con le voci gia' presenti (quelle "bundled" restano).

Formato di una voce (visto nel file della GUI):
  {"name": ..., "command": "motore.exe", "working_folder": "...",
   "protocol": "uci", "options": [{"name","type","default","min","max","value"}]}

I percorsi restano in CCRL\engines\ (working_folder assoluto): non viene
duplicato niente. Le opzioni dichiarate dal motore vengono riportate tutte,
con "value" = default tranne quelle impostate qui (Threads, Hash, Ponder,
OwnBook, SyzygyPath).

IMPORTANTE: chiudere Myracle prima di lanciare lo script, altrimenti alla
chiusura la GUI riscrive il file e le voci aggiunte spariscono.

Uso (dalla cartella CCRL):
  python tools\myracle_import.py                      anteprima e scrittura
  python tools\myracle_import.py --dry-run            solo anteprima
  python tools\myracle_import.py --threads 4 --hash 2048
  python tools\myracle_import.py --engines Caissa_2.0,Stockfish_19
  python tools\myracle_import.py --no-syzygy --no-tc
  python tools\myracle_import.py --restore            ripristina il backup
"""
import argparse
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys

CCRL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ENGINES_DIR = os.path.join(CCRL_ROOT, "engines")
DEFAULT_MYRACLE = r"C:\Users\Francesco\Desktop\myracle"
TB_DIR = os.path.join(CCRL_ROOT, "tb", "syzygy", "3-4-5")


def parse_uci_options(path):
    """uci_options.txt -> lista di opzioni nel formato di Myracle."""
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        m = re.match(r"option name (.+?) type (\w+)(.*)", line.strip())
        if not m:
            continue
        name, typ, rest = m.group(1), m.group(2), m.group(3)
        o = {"name": name, "type": typ}
        d = re.search(r"default (.*?)(?= min | max | var |$)", rest)
        if typ == "button":
            out.append(o)
            continue
        if typ == "spin":
            o["default"] = int(d.group(1)) if d and d.group(1).strip().lstrip("-").isdigit() else 0
            for k in ("min", "max"):
                mm = re.search(rf"{k} (-?\d+)", rest)
                if mm:
                    o[k] = int(mm.group(1))
        elif typ == "check":
            o["default"] = bool(d and d.group(1).strip() == "true")
        elif typ == "combo":
            o["default"] = d.group(1).strip() if d else ""
            o["var"] = re.findall(r"var (.+?)(?= var |$)", rest)
        else:                                   # string
            o["default"] = d.group(1).strip() if d else ""
        o["value"] = o["default"]
        out.append(o)
    return out


def apply_values(options, threads, hash_mb, syzygy):
    """Imposta i valori del torneo sulle opzioni che il motore espone davvero."""
    by_name = {o["name"]: o for o in options}
    if "Threads" in by_name:
        by_name["Threads"]["value"] = min(threads, by_name["Threads"].get("max", threads))
    if "Hash" in by_name:
        by_name["Hash"]["value"] = min(hash_mb, by_name["Hash"].get("max", hash_mb))
    for n in ("Ponder", "OwnBook"):
        if n in by_name:
            by_name[n]["value"] = False
    if syzygy and "SyzygyPath" in by_name:
        by_name["SyzygyPath"]["value"] = syzygy
    return options


def build_entries(selected, threads, hash_mb, syzygy):
    entries = []
    for folder in sorted(os.listdir(ENGINES_DIR)):
        d = os.path.join(ENGINES_DIR, folder)
        if not os.path.isdir(d) or (selected and folder not in selected):
            continue
        exes = glob.glob(os.path.join(d, "**", "*.exe"), recursive=True)
        if len(exes) != 1:
            print(f"  ATTENZIONE: {folder}: {len(exes)} eseguibili, saltato")
            continue
        exe = exes[0]
        opts = parse_uci_options(os.path.join(d, "uci_options.txt"))
        if not opts:
            print(f"  ATTENZIONE: {folder}: uci_options.txt mancante, opzioni non impostate")
        entries.append({
            "name": folder.replace("_", " ").replace("Cronus-", "Cronus "),
            "command": os.path.basename(exe),
            "working_folder": os.path.dirname(exe).replace("\\", "/"),
            "protocol": "uci",
            "options": apply_values(opts, threads, hash_mb, syzygy),
        })
    return entries


def add_time_control(cfg_dir, base, inc, name):
    """Aggiunge un time control alla lista della GUI, se non c'e' gia'."""
    p = os.path.join(cfg_dir, "time_control.json")
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    lst = d.get("time_control", [])
    for t in lst:
        if t.get("name") == name:
            return f"time control '{name}' gia' presente"
    lst.append({
        "time_control": [{"moves": 0, "base": base, "increment": inc, "gui_base_minutes": False}],
        "name": name, "mode": "tournament", "fixed_time": 0, "nodes": 0, "depth": 0, "margin_ms": 50,
    })
    d["time_control"] = lst
    shutil.copy2(p, p + ".bak")
    json.dump(d, open(p, "w", encoding="utf-8"), indent="\t")
    return f"aggiunto time control '{name}' ({base}s + {inc}s)"


def main():
    ap = argparse.ArgumentParser(description="Importa i motori CCRL nella GUI Myracle",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--myracle", default=DEFAULT_MYRACLE, help=f"cartella di Myracle (default {DEFAULT_MYRACLE})")
    ap.add_argument("--engines", help="solo questi motori (nomi delle cartelle, separati da virgola)")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--hash", type=int, default=2048)
    ap.add_argument("--no-syzygy", action="store_true", help="non impostare SyzygyPath")
    ap.add_argument("--no-tc", action="store_true", help="non aggiungere il time control CCRL")
    ap.add_argument("--tc", default="1690+19", help="time control da aggiungere (default 1690+19)")
    ap.add_argument("--replace-all", action="store_true",
                    help="sostituisce l'intera lista invece di fondersi con quella esistente")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restore", action="store_true", help="ripristina engines.json.gz dal backup")
    a = ap.parse_args()

    cfg_dir = os.path.join(a.myracle, "config")
    target = os.path.join(cfg_dir, "engines.json.gz")
    backup = target + ".bak"
    if not os.path.isdir(cfg_dir):
        sys.exit(f"ERRORE: cartella di Myracle non valida: {a.myracle}")

    if a.restore:
        if not os.path.exists(backup):
            sys.exit(f"ERRORE: nessun backup in {backup}")
        shutil.copy2(backup, target)
        print(f"ripristinato {target} dal backup")
        return

    running = "myracle.exe" in subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    if running and not a.dry_run:
        sys.exit("ERRORE: Myracle e' in esecuzione: chiuderlo prima, altrimenti alla chiusura\n"
                 "        riscrive config\\engines.json.gz e le voci aggiunte vanno perse.")

    selected = {x.strip() for x in a.engines.split(",")} if a.engines else None
    syzygy = "" if a.no_syzygy else (TB_DIR if os.path.isdir(TB_DIR) else "")
    print(f"motori da CCRL\\engines\\ (Threads={a.threads}, Hash={a.hash}, "
          f"Syzygy={'no' if not syzygy else syzygy}):")
    entries = build_entries(selected, a.threads, a.hash, syzygy)
    if not entries:
        sys.exit("ERRORE: nessun motore trovato")

    existing = []
    if os.path.exists(target) and not a.replace_all:
        existing = json.loads(gzip.open(target, "rb").read().decode("utf-8"))
    new_names = {e["name"] for e in entries}
    merged = [e for e in existing if e.get("name") not in new_names] + entries

    for e in entries:
        vals = {o["name"]: o.get("value") for o in e["options"]}
        shown = ", ".join(f"{k}={vals[k]}" for k in ("Threads", "Hash", "Ponder", "OwnBook") if k in vals)
        print(f"  {e['name']:24} {e['command']:46} {shown}")
    print(f"\nvoci totali nel file: {len(merged)} ({len(existing) - (len(merged) - len(entries))} sostituite, "
          f"{len(merged) - len(entries)} mantenute)")

    if a.dry_run:
        print("\n[dry-run] niente scritto.")
        return

    if os.path.exists(target) and not os.path.exists(backup):
        shutil.copy2(target, backup)
        print(f"backup: {backup}")
    data = json.dumps(merged, indent=1, ensure_ascii=False).encode("utf-8")
    with gzip.open(target, "wb") as f:
        f.write(data)
    print(f"scritto: {target}")

    if not a.no_tc:
        m = re.match(r"(\d+)\+(\d+)", a.tc)
        if m:
            msg = add_time_control(cfg_dir, int(m.group(1)), int(m.group(2)), f"CCRL 40/15 ({a.tc})")
            if msg:
                print(msg)
    print("\nRiaprire Myracle: i motori compaiono nella lista senza aggiungerli a mano.")


if __name__ == "__main__":
    main()
