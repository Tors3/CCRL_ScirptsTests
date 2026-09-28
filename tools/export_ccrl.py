#!/usr/bin/env python3
r"""
export_ccrl.py - prepara il PGN di un gauntlet per l'invio al CCRL.

Segue la convenzione dei file inviati dai tester CCRL (es. Gabor Szots):

  nome file  [Nome Cognome AAAA-MM-GG] <Event> (hash <N>MB) (book <libro>) (egtb <N>-man).pgn
  zip        stesso nome con "_" al posto di spazi, parentesi e quadre
  Event      "<motore sotto test> - <Mes GG>"   (data della prima partita, es. "Sep 22")
  Site       la localita' del tester
  giocatori  "<Motore versione> 64-bit" (+ " <N>CPU" se Threads > 1)

Dai PGN del gauntlet prende ogni partita conclusa una sola volta (i doppioni da
ripresa vengono scartati tenendo la prima), cambia solo Event, Site e i nomi dei
giocatori, e lascia invariato tutto il resto (mosse, commenti, TimeControl...).
I file originali del gauntlet non vengono toccati.

Uso (dalla cartella CCRL):
  python tools\export_ccrl.py --gauntlet-dir gauntlets\<nome> --name "Francesco Torsello" --site "Citta"
  opzioni: --date AAAA-MM-GG (default oggi), --egtb 5, --no-zip
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import zipfile

CCRL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def blocks(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    for b in re.split(r"\n\s*\n(?=\[)", text):
        b = b.strip("\n")
        if b.startswith("["):
            yield b, dict(re.findall(r'^\[(\w+) "(.*)"\]', b, re.M))


def slot(h):
    m = re.search(r"node(\d+) pass(\d+)(?: r(\d+))?$", h.get("Event", ""))
    if not m:
        return (h.get("Event"), h.get("Round"))
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or h.get("Round", "0") or 0)


def ccrl_name(name, cpus):
    """'Stockfish 19' -> 'Stockfish 19 64-bit 4CPU'; non raddoppia i suffissi gia' presenti."""
    n = re.sub(r"\s+\d+CPU$", "", name.strip())
    if not re.search(r"\b64-bit$", n):
        n += " 64-bit"
    return n + (f" {cpus}CPU" if cpus > 1 else "")


def bat_value(bat, key):
    m = re.search(rf"(?m)^set {key}=(.*?)\s*$", open(bat, encoding="ascii", errors="replace").read())
    return m.group(1).strip() if m else ""


def main():
    ap = argparse.ArgumentParser(description="Esporta un gauntlet nel formato di invio CCRL",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--gauntlet-dir", required=True)
    ap.add_argument("--name", required=True, help='nome e cognome del tester, es. "Francesco Torsello"')
    ap.add_argument("--site", required=True, help="localita' (tag Site)")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="data dell'invio (AAAA-MM-GG)")
    ap.add_argument("--egtb", type=int, default=None, help="pezzi delle tablebase (default: dal percorso Syzygy)")
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()

    gdir = a.gauntlet_dir if os.path.isabs(a.gauntlet_dir) else os.path.join(CCRL_ROOT, a.gauntlet_dir)
    bat = os.path.join(gdir, "scripts", "gauntlet.bat")
    cfg = json.load(open(os.path.join(gdir, "config", "engines.json"), encoding="utf-8"))
    threads = int(bat_value(bat, "THREADS") or 1)
    hash_mb = bat_value(bat, "HASH")
    book = os.path.splitext(os.path.basename(bat_value(bat, "BOOK") or "avt-book-2026.pgn"))[0]
    syz = bat_value(bat, "SYZYGY_PATH")
    egtb = a.egtb or (max(int(x) for x in re.findall(r"\d", os.path.basename(syz))) if syz else 0)

    # partite uniche, in ordine cronologico
    first = {}
    games = []
    for p in sorted(glob.glob(os.path.join(gdir, "pgn", "node*.pgn"))):
        for b, h in blocks(p):
            if h.get("Result") not in ("1-0", "0-1", "1/2-1/2"):
                continue
            k = (slot(h), h.get("White"), h.get("Black"))
            e = h.get("GameEndTime", "")
            games.append((e, k, b, h))
            if k not in first or e < first[k]:
                first[k] = e
    unique = sorted([g for g in games if first[g[1]] == g[0]], key=lambda g: g[0])
    if not unique:
        sys.exit("ERRORE: nessuna partita conclusa")

    start = min(datetime.date(*map(int, g[3]["Date"].split("."))) for g in unique if g[3].get("Date"))
    seed = ccrl_name(cfg["seed"]["name"], threads)
    event = f"{seed} - {start.strftime('%b')} {start.day}"

    names = {e["name"]: ccrl_name(e["name"], threads) for e in [cfg["seed"]] + cfg["opponents"]}
    out = []
    for i, (_, _, b, h) in enumerate(unique, 1):
        b = re.sub(r'(?m)^\[Event ".*"\]$', lambda m: f'[Event "{event}"]', b)
        b = re.sub(r'(?m)^\[Site ".*"\]$', lambda m: f'[Site "{a.site}"]', b)
        b = re.sub(r'(?m)^\[Round ".*"\]$', lambda m: f'[Round "{i}"]', b)
        b = re.sub(r'(?m)^\[(White|Black) "(.*)"\]$',
                   lambda m: f'[{m.group(1)} "{names.get(m.group(2), ccrl_name(m.group(2), threads))}"]', b)
        out.append(b)

    base = f"[{a.name} {a.date}] {event} (hash {hash_mb}MB) (book {book}) (egtb {egtb}-man)"
    res = os.path.join(gdir, "results")
    os.makedirs(res, exist_ok=True)
    pgn_path = os.path.join(res, base + ".pgn")
    with open(pgn_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n\n".join(out) + "\n\n")
    print(f"PGN: {pgn_path}  ({len(out)} partite)")

    if not a.no_zip:
        zname = re.sub(r"_+", "_", re.sub(r"[\s\[\]()]+", "_", base)).strip("_") + ".zip"
        zpath = os.path.join(res, zname)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(pgn_path, os.path.basename(pgn_path))
        print(f"ZIP: {zpath}  ({os.path.getsize(zpath) // 1024} KB)")
    print(f"\nEvent: {event}\nGiocatori: " + ", ".join(sorted(set(names.values()))))


if __name__ == "__main__":
    main()
