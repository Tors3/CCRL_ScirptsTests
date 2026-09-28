#!/usr/bin/env python3
r"""
chain_after.py - avvia un gauntlet quando un altro e' davvero finito.

Controlla ogni --every secondi il gauntlet in corso (--wait-dir):
  - se i suoi driver (run_node.py) sono ancora attivi -> aspetta;
  - se sono fermi e i PGN contengono tutte le partite previste (--expect) ->
    avvia l'attivita' pianificata --then-task ed esce;
  - se sono fermi, i log dicono "FINE" ma mancano partite (partite non registrate)
    -> rilancia --retry-task per completarle (al massimo --max-retry volte);
  - se sono fermi senza "FINE" (fermato a mano) -> non fa nulla e continua ad
    aspettare: non parte mai da solo un torneo se il precedente e' stato interrotto.

Va lanciato con pythonw tramite l'Utilita' di pianificazione (tools\chain_after.bat),
cosi' non dipende da nessuna finestra o applicazione. Scrive in <wait-dir>\logs\chain.log.

Uso:
  pythonw tools\chain_after.py --wait-dir gauntlets\A --expect 870 \
      --retry-task "CCRL Gauntlet A" --then-task "CCRL Gauntlet B"
"""
import argparse
import datetime
import glob
import os
import re
import subprocess
import sys
import time

CCRL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def log(path, msg):
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def drivers_running(gdir):
    """True se c'e' un run_node.py di QUESTO gauntlet in esecuzione."""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_node.py*' } | "
          "ForEach-Object { $_.ExecutablePath + '|' + $_.CommandLine }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    scripts = os.path.normcase(os.path.join(gdir, "scripts"))
    return any(scripts in os.path.normcase(l) for l in out.splitlines())


def unique_games(gdir):
    seen = set()
    for f in glob.glob(os.path.join(gdir, "pgn", "node*.pgn")):
        for b in re.split(r"\n\s*\n(?=\[)", open(f, encoding="utf-8", errors="replace").read()):
            h = dict(re.findall(r'^\[(\w+) "(.*)"\]', b, re.M))
            if h.get("Result") in ("1-0", "0-1", "1/2-1/2"):
                m = re.search(r"node(\d+) pass(\d+)(?: r(\d+))?$", h.get("Event", ""))
                rnd = m.group(3) or h.get("Round") if m else h.get("Round")
                seen.add((m.groups()[:2] if m else h.get("Event"), rnd, h.get("White"), h.get("Black")))
    return len(seen)


def finished_cleanly(gdir):
    """Ogni log dei driver termina (dopo l'ultimo 'start |') con una riga FINE."""
    logs = glob.glob(os.path.join(gdir, "logs", "node*_driver.log"))
    if not logs:
        return False
    for l in logs:
        lines = open(l, encoding="utf-8", errors="replace").read().splitlines()
        starts = [i for i, x in enumerate(lines) if "start |" in x]
        if not starts or not any("FINE |" in x for x in lines[starts[-1]:]):
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-dir", required=True)
    ap.add_argument("--expect", type=int, required=True, help="partite totali del gauntlet da aspettare")
    ap.add_argument("--then-task", required=True)
    ap.add_argument("--retry-task", required=True)
    ap.add_argument("--every", type=int, default=120)
    ap.add_argument("--max-retry", type=int, default=2)
    a = ap.parse_args()
    gdir = a.wait_dir if os.path.isabs(a.wait_dir) else os.path.join(CCRL_ROOT, a.wait_dir)
    lp = os.path.join(gdir, "logs", "chain.log")
    log(lp, f"in attesa: {a.expect} partite, poi '{a.then_task}'")
    retries = 0
    while True:
        try:
            if not drivers_running(gdir):
                n = unique_games(gdir)
                if n >= a.expect:
                    log(lp, f"completo ({n} partite): avvio '{a.then_task}'")
                    r = subprocess.run(["schtasks", "/run", "/tn", a.then_task], capture_output=True, text=True)
                    log(lp, (r.stdout or r.stderr).strip())
                    return
                if finished_cleanly(gdir) and retries < a.max_retry:
                    retries += 1
                    log(lp, f"FINE ma solo {n}/{a.expect} partite: rilancio '{a.retry_task}' ({retries}/{a.max_retry})")
                    subprocess.run(["schtasks", "/run", "/tn", a.retry_task], capture_output=True, text=True)
                    time.sleep(300)
                    continue
        except Exception as e:
            log(lp, f"errore nel controllo: {e}")
        time.sleep(a.every)


if __name__ == "__main__":
    main()
