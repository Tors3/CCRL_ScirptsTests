#!/usr/bin/env python3
"""
merge_results.py - unisce i PGN delle istanze (pgn\node*.pgn) e calcola la
classifica del gauntlet dal punto di vista del motore sotto test.

Output (in results/):
  all_games.pgn   tutte le partite (node0 + node1, in ordine di file)
  summary.md      tabella per avversario + totale, terminazioni, controllo coppie, stima durata
  results.csv     stessi dati in CSV

Uso: python merge_results.py [--gauntlet-dir DIR] [--seed "Caissa 2.0"]
Se config\ratings.csv contiene i rating CCRL degli avversari (name,rating),
calcola anche il performance rating stimato.
"""
import argparse
import csv
import glob
import json
import math
import os
import re
from collections import Counter, defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_pgn(path):
    """Generatore di (headers dict, movetext str)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        headers, moves, in_moves = {}, [], False
        for line in f:
            if line.startswith("["):
                if in_moves:
                    yield headers, " ".join(moves)
                    headers, moves, in_moves = {}, [], False
                m = re.match(r'\[(\w+) "(.*)"\]', line)
                if m:
                    headers[m.group(1)] = m.group(2)
            elif line.strip():
                in_moves = True
                moves.append(line.strip())
        if headers:
            yield headers, " ".join(moves)


def elo_from_score(s):
    if s <= 0:
        return -math.inf
    if s >= 1:
        return math.inf
    return -400 * math.log10(1 / s - 1)


def stats_row(name, results):
    """results: lista di punteggi 1/0.5/0 dal punto di vista del seed."""
    n = len(results)
    w = sum(1 for r in results if r == 1)
    d = sum(1 for r in results if r == 0.5)
    l = n - w - d
    if n == 0:
        return dict(name=name, games=0, wins=0, draws=0, losses=0, score=0, pct=0, elo=0, err=0)
    s = (w + d / 2) / n
    var = sum((r - s) ** 2 for r in results) / max(n - 1, 1)
    sd = math.sqrt(var / n)
    elo = elo_from_score(s)
    lo, hi = elo_from_score(max(s - 1.96 * sd, 1e-9)), elo_from_score(min(s + 1.96 * sd, 1 - 1e-9))
    err = (hi - lo) / 2 if math.isfinite(hi) and math.isfinite(lo) else float("inf")
    return dict(name=name, games=n, wins=w, draws=d, losses=l, score=w + d / 2, pct=100 * s, elo=elo, err=err)


def fmt_elo(x):
    return "n/a" if not math.isfinite(x) else f"{x:+.0f}"


def fmt_row(r):
    base = f"| {r['name']} | {r['games']} | {r['wins']} | {r['draws']} | {r['losses']} | {r['score']:g} | {r['pct']:.1f} | "
    return base + (f"{fmt_elo(r['elo'])} ± {r['err']:.0f} |" if math.isfinite(r["err"]) else f"{fmt_elo(r['elo'])} |")


def duration_s(h):
    m = re.match(r"(\d+):(\d+):(\d+)", h.get("GameDuration", ""))
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gauntlet-dir", default=os.path.abspath(os.path.join(SCRIPT_DIR, "..")))
    ap.add_argument("--seed", default=None, help="nome del motore sotto test (default: config/engines.json)")
    a = ap.parse_args()
    gd = a.gauntlet_dir
    seed = a.seed
    if seed is None:
        seed = json.load(open(os.path.join(gd, "config", "engines.json"), encoding="utf-8"))["seed"]["name"]
    res_dir = os.path.join(gd, "results")
    os.makedirs(res_dir, exist_ok=True)

    pgns = sorted(glob.glob(os.path.join(gd, "pgn", "node*.pgn")))
    if not pgns:
        raise SystemExit("nessun pgn\\node*.pgn trovato")

    per_opp = defaultdict(list)      # nome avversario -> punteggi
    per_color = defaultdict(list)    # "white"/"black" -> punteggi del seed
    per_engine = defaultdict(list)   # classifica generale (utile in modalita' roundrobin)
    terminations = Counter()
    pair_check = Counter()           # (opponent, event, round, file) -> partite
    durations = []
    unfinished = 0
    with open(os.path.join(res_dir, "all_games.pgn"), "w", encoding="utf-8") as out:
        for p in pgns:
            for h, mv in parse_pgn(p):
                out.write("".join(f'[{k} "{v}"]\n' for k, v in h.items()) + "\n" + mv + "\n\n")
                r = h.get("Result", "*")
                if r not in ("1-0", "0-1", "1/2-1/2"):
                    unfinished += 1
                    continue
                d = duration_s(h)
                if d:
                    durations.append(d)
                w, b = h.get("White"), h.get("Black")
                ws = {"1-0": 1, "0-1": 0, "1/2-1/2": 0.5}[r]
                per_engine[w].append(ws)
                per_engine[b].append(1 - ws)
                if seed not in (w, b):
                    continue
                opp = b if w == seed else w
                sc = ws if w == seed else 1 - ws
                per_opp[opp].append(sc)
                per_color["white" if w == seed else "black"].append(sc)
                terminations[(opp, h.get("Termination", "?"))] += 1
                pair_check[(opp, h.get("Event", ""), h.get("Round", ""), os.path.basename(p))] += 1

    ratings = {}
    rp = os.path.join(gd, "config", "ratings.csv")
    if os.path.exists(rp):
        for row in csv.DictReader(open(rp, encoding="utf-8")):
            try:
                ratings[row["name"].strip()] = float(row["rating"])
            except (KeyError, ValueError):
                pass

    rows = sorted((stats_row(o, v) for o, v in per_opp.items()), key=lambda r: -r["pct"])
    total = stats_row("TOTALE", [s for v in per_opp.values() for s in v])

    perf = None
    rated = [(o, per_opp[o]) for o in per_opp if o in ratings]
    if rated:
        n = sum(len(v) for _, v in rated)
        avg_r = sum(ratings[o] * len(v) for o, v in rated) / n
        s = sum(sum(v) for _, v in rated) / n
        perf = (avg_r, s, n, avg_r + elo_from_score(s))

    lines = [f"# Gauntlet {seed} - risultati", "",
             f"Sorgenti: {', '.join(os.path.basename(p) for p in pgns)} | partite valide: {total['games']} | non terminate/ignorate: {unfinished}", "",
             "| Avversario | Partite | +W | =D | -L | Punti | % | Elo diff (±95%) |", "|---|---|---|---|---|---|---|---|"]
    lines += [fmt_row(r) for r in rows + [total]]
    lines += ["", "Per colore del motore sotto test:"]
    for c in ("white", "black"):
        r = stats_row(c, per_color[c])
        lines.append(f"- {c}: {r['games']} partite, {r['pct']:.1f}% (+{r['wins']} ={r['draws']} -{r['losses']})")
    if perf:
        lines += ["", f"Performance rating stimato: **{perf[3]:.0f}** (rating medio avversari {perf[0]:.0f} su {perf[2]} partite, score {100*perf[1]:.1f}%)"]
    else:
        lines += ["", "Performance rating: compilare config\\ratings.csv (name,rating) con i rating CCRL degli avversari."]
    if len(per_engine) > 2 and any(e != seed and len(per_engine[e]) > len(per_opp.get(e, [])) for e in per_engine):
        lines += ["", "## Classifica generale (tutte le partite)", "", "| # | Motore | Partite | Punti | % | Elo diff (±95%) |", "|---|---|---|---|---|---|"]
        gen = sorted((stats_row(e, v) for e, v in per_engine.items()), key=lambda r: -r["pct"])
        for i, r in enumerate(gen, 1):
            lines.append(f"| {i} | {r['name']} | {r['games']} | {r['score']:g} | {r['pct']:.1f} | {fmt_elo(r['elo'])} ± {r['err']:.0f} |")
    if durations:
        avg = sum(durations) / len(durations)
        lines += ["", "## Durata", "",
                  f"Durata media partita: {avg/60:.0f} min (min {min(durations)/60:.0f}, max {max(durations)/60:.0f}, su {len(durations)} partite)."]
    lines += ["", "## Terminazioni", "", "| Avversario | Terminazione | N |", "|---|---|---|"]
    for (o, t), n in sorted(terminations.items()):
        lines.append(f"| {o} | {t} | {n} |")
    odd = [(k, n) for k, n in pair_check.items() if n != 2]
    lines += ["", "## Controllo coppie (ogni apertura = 2 partite a colori invertiti)", ""]
    lines.append("OK: tutte le coppie sono complete." if not odd else
                 "ATTENZIONE, coppie incomplete/duplicate (avversario, event, round, file -> partite):")
    for k, n in sorted(odd):
        lines.append(f"- {k} -> {n}")
    open(os.path.join(res_dir, "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

    with open(os.path.join(res_dir, "results.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["opponent", "games", "wins", "draws", "losses", "score", "pct", "elo_diff", "elo_err95"])
        for r in rows + [total]:
            wr.writerow([r["name"], r["games"], r["wins"], r["draws"], r["losses"], r["score"], f"{r['pct']:.2f}",
                         "" if not math.isfinite(r["elo"]) else f"{r['elo']:.1f}",
                         "" if not math.isfinite(r["err"]) else f"{r['err']:.1f}"])
    print("\n".join(lines))
    print(f"\nscritto: {res_dir}\\summary.md, results.csv, all_games.pgn")


if __name__ == "__main__":
    main()
