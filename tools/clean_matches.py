#!/usr/bin/env python3
r"""
clean_matches.py - rimuove dai PGN di un gauntlet le partite non valide e
azzera i match a cui appartengono, cosi' che vengano rigiocati da capo.

Serve quando un gruppo di partite e' stato giocato in condizioni sbagliate
(motore crashato, CPU sovraccarica, parametri errati): non basta togliere le
singole partite, perche' il match resterebbe "a meta'" con uno stato fastchess
(.json) che non corrisponde piu' al PGN. Lo script quindi:

  1. individua i match da invalidare, per uno di questi criteri:
       --after AAAA-MM-GGTHH:MM:SS   partite terminate dopo quell'istante
       --termination abandoned       partite con quel tag Termination
       --match "Event|Motore A|Motore B"   un match specifico
  2. rimuove dai PGN TUTTE le partite di quei match (anche quelle valide:
     un match si rigioca intero, altrimenti le aperture si sfalsano);
  3. cancella i .json di stato di quei match;
  4. rigenera pgn\games\ (una partita per file).

I PGN originali vengono salvati con estensione .bak prima di essere riscritti.

Uso (dalla cartella CCRL):
  python tools\clean_matches.py --gauntlet-dir gauntlets\<nome> --dry-run
  python tools\clean_matches.py --gauntlet-dir gauntlets\<nome> \
      --after 2026-09-22T16:49:57 --termination abandoned
"""
import argparse
import datetime
import glob
import os
import re
import shutil
import sys

CCRL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def games_of(path):
    """Genera (blocco_testo, headers) per ogni partita del PGN."""
    text = open(path, encoding="utf-8", errors="replace").read()
    for block in re.split(r"\n\s*\n(?=\[)", text):
        block = block.strip("\n")
        if block.startswith("["):
            yield block, dict(re.findall(r'^\[(\w+) "(.*)"\]', block, re.M))


def end_time(h):
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)", h.get("GameEndTime", ""))
    return datetime.datetime(*map(int, m.groups())) if m else None


def match_key(h):
    return (h.get("Event", ""), frozenset((h.get("White", ""), h.get("Black", ""))))


def slug(name):
    return re.sub(r"[^A-Za-z0-9.\-]+", "_", name)


def main():
    ap = argparse.ArgumentParser(description="Invalida e azzera match di un gauntlet",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--gauntlet-dir", required=True)
    ap.add_argument("--after", help="AAAA-MM-GGTHH:MM:SS: invalida le partite terminate dopo")
    ap.add_argument("--termination", action="append", default=[],
                    help="invalida le partite con questo tag Termination (ripetibile)")
    ap.add_argument("--match", action="append", default=[],
                    help='invalida un match: "Event|Motore A|Motore B"')
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    gdir = a.gauntlet_dir if os.path.isabs(a.gauntlet_dir) else os.path.join(CCRL_ROOT, a.gauntlet_dir)
    pgn_dir, log_dir = os.path.join(gdir, "pgn"), os.path.join(gdir, "logs")
    pgns = sorted(glob.glob(os.path.join(pgn_dir, "*.pgn")))
    if not pgns:
        sys.exit(f"ERRORE: nessun PGN in {pgn_dir}")
    cutoff = datetime.datetime.fromisoformat(a.after) if a.after else None
    if not (cutoff or a.termination or a.match):
        sys.exit("ERRORE: indicare almeno un criterio (--after / --termination / --match)")

    bad = set()
    for m in a.match:
        ev, w, b = m.split("|")
        bad.add((ev, frozenset((w, b))))
    reasons = {}
    for p in pgns:
        for _, h in games_of(p):
            why = None
            if cutoff and end_time(h) and end_time(h) > cutoff:
                why = f"terminata dopo {a.after}"
            elif h.get("Termination") in a.termination:
                why = f"Termination={h.get('Termination')}"
            if why:
                k = match_key(h)
                bad.add(k)
                reasons.setdefault(k, why)

    if not bad:
        print("nessun match da invalidare.")
        return

    print(f"match da invalidare ({len(bad)}):")
    for ev, pair in sorted(bad, key=lambda k: (k[0], sorted(k[1]))):
        print(f"  {ev} | {' vs '.join(sorted(pair))}   [{reasons.get((ev, pair), 'indicato a mano')}]")

    removed = kept = 0
    for p in pgns:
        keep_blocks = []
        for block, h in games_of(p):
            if match_key(h) in bad:
                removed += 1
            else:
                keep_blocks.append(block)
                kept += 1
        if not a.dry_run:
            if not os.path.exists(p + ".bak"):
                shutil.copy2(p, p + ".bak")
            with open(p, "w", encoding="utf-8") as f:
                f.write("".join(b + "\n\n" for b in keep_blocks))
    print(f"\npartite rimosse: {removed} | mantenute: {kept}")

    jsons = []
    for ev, pair in bad:
        node = re.search(r"node(\d+)", ev)
        pas = re.search(r"pass(\d+)", ev)
        if not (node and pas):
            continue
        for a_, b_ in ((x, y) for x in pair for y in pair if x != y):
            jsons += glob.glob(os.path.join(log_dir, f"node{node.group(1)}_p{pas.group(1)}_"
                                                     f"{slug(a_)}_vs_{slug(b_)}.json"))
    for j in sorted(set(jsons)):
        print(f"  cancello stato: {os.path.basename(j)}")
        if not a.dry_run:
            os.remove(j)

    games_dir = os.path.join(pgn_dir, "games")
    if os.path.isdir(games_dir):
        n = len(os.listdir(games_dir))
        print(f"\nrigenero pgn\\games\\ ({n} file da rifare)")
        if not a.dry_run:
            shutil.rmtree(games_dir)
            sys.path.insert(0, os.path.join(gdir, "scripts"))
            for node in sorted({re.search(r"node(\d+)", os.path.basename(p)).group(1)
                                for p in pgns if re.search(r"node(\d+)", os.path.basename(p))}):
                os.environ["NODE"] = node
                os.environ["GAUNTLET_DIR"] = gdir
                for mod in [m for m in list(sys.modules) if m == "run_node"]:
                    del sys.modules[mod]
                import run_node
                run_node.split_all_pgns()
            print(f"  ricreati {len(os.listdir(games_dir))} file")
    if a.dry_run:
        print("\n[dry-run] niente modificato.")


if __name__ == "__main__":
    main()
