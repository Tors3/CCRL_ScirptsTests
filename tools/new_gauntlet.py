#!/usr/bin/env python3
r"""
new_gauntlet.py - crea una nuova cartella di gauntlet pronta da lanciare.

Legge i motori da CCRL\engines\<Nome>_<versione>\ (eseguibile + uci_options.txt
prodotto dalla verifica UCI), scrive config\engines.json e config\ratings.csv,
copia gli script da tools\gauntlet_template\scripts\ e personalizza i parametri
in gauntlet.bat (nome evento, time control, Threads, Hash, partite, ...).

Esempi (dalla cartella CCRL):

  python new_gauntlet.py --list
      elenca i motori disponibili in engines\ con il loro "id name"

  python new_gauntlet.py --seed Caissa_2.0
      gauntlet di Caissa contro TUTTI gli altri motori, 40 partite per avversario

  python new_gauntlet.py --seed Triumviratus_7.0 --exclude Caissa_2.0,Coda_0.9.3
      come sopra ma senza quei due avversari

  python new_gauntlet.py --seed Triumviratus_7.0 --opponents Stockfish_19,Berserk_14,Clover_9.0
      solo contro gli avversari indicati

  python new_gauntlet.py --seed Caissa_2.0 --mode roundrobin --engines all
      tutti contro tutti (attenzione: 190 accoppiamenti)

  python new_gauntlet.py --seed Caissa_2.0 --threads 2 --hash 1024 --tc 845+10 --games 20
      condizioni 2CPU (la regola di default e' 512 MB di hash per core)

I nomi dei motori sono i nomi delle cartelle in engines\ (bastano prefissi non
ambigui, senza distinzione fra maiuscole e minuscole: "stock" -> Stockfish_19).
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import sys

CCRL_ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINES_DIR = os.path.join(CCRL_ROOT, "engines")
TEMPLATE_DIR = os.path.join(CCRL_ROOT, "tools", "gauntlet_template", "scripts")
GAUNTLETS_DIR = os.path.join(CCRL_ROOT, "gauntlets")


def discover_engines():
    """{nome cartella: dict} per ogni motore in engines\\ con un solo .exe."""
    out = {}
    for folder in sorted(os.listdir(ENGINES_DIR)):
        d = os.path.join(ENGINES_DIR, folder)
        if not os.path.isdir(d):
            continue
        exes = glob.glob(os.path.join(d, "**", "*.exe"), recursive=True)
        if len(exes) != 1:
            print(f"ATTENZIONE: {folder}: {len(exes)} eseguibili trovati, cartella ignorata")
            continue
        opt_file = os.path.join(d, "uci_options.txt")
        opts = open(opt_file, encoding="utf-8").read() if os.path.exists(opt_file) else ""
        names = re.findall(r"^option name (.+?) type", opts, re.M)
        uci_id = re.search(r"^id name (.+)$", opts, re.M)
        options = {"Threads": "${THREADS}", "Hash": "${HASH}"}
        if "Ponder" in names:
            options["Ponder"] = "false"
        if "OwnBook" in names:          # Coda 0.9.3 ha OwnBook=true di default
            options["OwnBook"] = "false"
        # nome leggibile: Stockfish_19 -> "Stockfish 19", Quanticade_Cronus-3.0 -> "Quanticade Cronus 3.0"
        display = folder.replace("_", " ").replace("Cronus-", "Cronus ")
        out[folder] = {"name": display, "folder": folder, "cmd": exes[0],
                       "dir": os.path.dirname(exes[0]), "options": options,
                       "uci_id": uci_id.group(1) if uci_id else "(uci_options.txt mancante)",
                       "has_syzygy": "SyzygyPath" in names}
    return out


def resolve(token, engines):
    """Accetta il nome esatto della cartella o un prefisso non ambiguo."""
    t = token.strip()
    if not t:
        return None
    if t in engines:
        return t
    matches = [k for k in engines if k.lower().startswith(t.lower())]
    if not matches:
        matches = [k for k in engines if t.lower() in k.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"ERRORE: nessun motore corrisponde a '{t}' (usa --list)")
    sys.exit(f"ERRORE: '{t}' e' ambiguo: {', '.join(matches)}")


def split_list(s):
    return [x for x in re.split(r"[,;]", s or "") if x.strip()]


def patch_bat(path, repl):
    """Sostituisce le righe 'set CHIAVE=...' in gauntlet.bat mantenendo i CRLF."""
    b = open(path, "rb").read()
    for key, value in repl.items():
        # [^\r\n]* per non consumare il CR: i .bat restano CRLF
        pat = re.compile(rb"(?m)^set " + re.escape(key.encode()) + rb"=[^\r\n]*")
        new = b"set " + key.encode() + b"=" + str(value).encode()
        if pat.search(b):
            b = pat.sub(lambda _m, n=new: n, b, count=1)   # lambda: il valore non e' un template
        else:
            print(f"ATTENZIONE: '{key}' non trovato in gauntlet.bat, non impostato")
    open(path, "wb").write(b)


def main():
    p = argparse.ArgumentParser(description="Crea una nuova cartella di gauntlet",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    p.add_argument("--list", action="store_true", help="elenca i motori disponibili ed esce")
    p.add_argument("--seed", help="motore sotto test (cartella in engines\\)")
    p.add_argument("--opponents", help="avversari, separati da virgola (default: tutti gli altri)")
    p.add_argument("--exclude", help="motori da escludere, separati da virgola")
    p.add_argument("--mode", choices=["gauntlet", "roundrobin"], default="gauntlet")
    p.add_argument("--threads", type=int, default=4, help="thread per motore (default 4)")
    p.add_argument("--hash", type=int, default=None, help="hash MB (default: 512 x threads)")
    p.add_argument("--tc", default="1690+19", help="time control fastchess (default 1690+19)")
    p.add_argument("--games", type=int, default=40,
                   help="partite per accoppiamento, totale sui 2 nodi (default 40)")
    p.add_argument("--passes", type=int, default=2, help="passate su tutti gli avversari (default 2)")
    p.add_argument("--concurrency", type=int, default=None,
                   help="partite in parallelo per nodo (default: 20 / threads)")
    p.add_argument("--name", help="nome della cartella (default: <data>_<seed>_<threads>CPU)")
    p.add_argument("--no-syzygy", action="store_true", help="non passare SyzygyPath ai motori")
    p.add_argument("--force", action="store_true", help="sovrascrive config e script se la cartella esiste")
    a = p.parse_args()

    engines = discover_engines()
    if a.list or not a.seed:
        print(f"{'cartella':26} {'nome nel PGN':24} {'Syzygy':7} id name")
        for k, e in engines.items():
            print(f"{k:26} {e['name']:24} {'si' if e['has_syzygy'] else 'no':7} {e['uci_id']}")
        if not a.seed:
            print("\nManca --seed: indicare il motore sotto test (vedi esempi con --help).")
        return

    seed_key = resolve(a.seed, engines)
    excluded = {resolve(x, engines) for x in split_list(a.exclude)}
    if a.opponents:
        opp_keys = [resolve(x, engines) for x in split_list(a.opponents)]
    else:
        opp_keys = [k for k in engines if k != seed_key]
    opp_keys = [k for k in opp_keys if k != seed_key and k not in excluded]
    if not opp_keys:
        sys.exit("ERRORE: nessun avversario selezionato")

    threads = a.threads
    hash_mb = a.hash if a.hash else 512 * threads
    concurrency = a.concurrency if a.concurrency else max(1, 20 // threads)
    # partite per accoppiamento = passes x rounds_per_pass x 2 colori x 2 nodi
    if a.games % (a.passes * 4) != 0:
        sys.exit(f"ERRORE: --games {a.games} non e' divisibile per passes x 4 "
                 f"({a.passes * 4}): scegliere un multiplo (es. {a.passes * 4 * 5})")
    rounds_per_pass = a.games // (a.passes * 4)

    name = a.name or f"{datetime.date.today():%Y-%m-%d}_{seed_key}_{threads}CPU"
    gdir = os.path.join(GAUNTLETS_DIR, name)
    if os.path.exists(gdir) and not a.force:
        sys.exit(f"ERRORE: {gdir} esiste gia' (usare --force per rigenerare config e script)")
    for sub in ("config", "scripts", "pgn/games", "logs", "results"):
        os.makedirs(os.path.join(gdir, sub), exist_ok=True)

    seed = engines[seed_key]
    opponents = [engines[k] for k in opp_keys]
    json.dump({"seed": seed, "opponents": opponents},
              open(os.path.join(gdir, "config", "engines.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)

    ratings_path = os.path.join(gdir, "config", "ratings.csv")
    if not os.path.exists(ratings_path) or a.force:
        with open(ratings_path, "w", encoding="utf-8") as f:
            f.write("name,rating\n" + "".join(f"{e['name']},\n" for e in opponents))

    for f in glob.glob(os.path.join(TEMPLATE_DIR, "*")):
        shutil.copy2(f, os.path.join(gdir, "scripts", os.path.basename(f)))

    tb = os.path.join(CCRL_ROOT, "tb", "syzygy", "3-4-5")
    patch_bat(os.path.join(gdir, "scripts", "gauntlet.bat"), {
        "MODE": a.mode,
        "HASH": hash_mb,
        "THREADS": threads,
        "TC": a.tc,
        "CONCURRENCY": concurrency,
        "PASSES": a.passes,
        "ROUNDS_PER_PASS": rounds_per_pass,
        "EVENT": f"CCRL 40/15 {a.mode} {seed['name']} {threads}CPU",
        "SYZYGY_PATH": "" if (a.no_syzygy or not os.path.isdir(tb)) else tb,
    })

    n_pair = len(opponents) if a.mode == "gauntlet" else (len(opponents) + 1) * len(opponents) // 2
    print(f"Creato: {gdir}")
    print(f"  modalita'      : {a.mode}")
    print(f"  sotto test     : {seed['name']}  ({os.path.relpath(seed['cmd'], CCRL_ROOT)})")
    print(f"  avversari      : {len(opponents)} -> {', '.join(e['name'] for e in opponents)}")
    print(f"  accoppiamenti  : {n_pair}, {a.games} partite ciascuno = {n_pair * a.games} partite totali")
    print(f"  condizioni     : tc={a.tc}  Threads={threads}  Hash={hash_mb} MB  "
          f"concurrency={concurrency}/nodo  ({a.passes} passate x {rounds_per_pass} aperture)")
    print(f"  Syzygy         : {'no' if a.no_syzygy or not os.path.isdir(tb) else tb}")
    print(f"\nControllare i parametri in scripts\\gauntlet.bat, poi avviare con:")
    print(f"  {os.path.join(gdir, 'scripts', 'start_all.bat')}")


if __name__ == "__main__":
    main()
