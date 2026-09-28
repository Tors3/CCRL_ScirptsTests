#!/usr/bin/env python3
r"""
verify_engine.py - verifica i motori in CCRL\engines\<Nome>_<versione>\.

Per ogni motore: avvio, "uci", "isready", una ricerca vera (go depth N) dalla
posizione iniziale e "quit". Controlla che risponda uciok/readyok e che trovi una
bestmove legale (un motore a cui manca la rete di solito si ferma qui), salva
l'elenco delle opzioni in uci_options.txt e stampa SHA256, id name e profondita'.

Uso (dalla cartella CCRL):
  python tools\verify_engine.py Integral_v8 Sirius_9.0 ...     motori indicati
  python tools\verify_engine.py --all                         tutti
  opzioni: --depth 14 (default 12)
"""
import argparse
import glob
import hashlib
import os
import queue
import re
import subprocess
import sys
import threading
import time

CCRL_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ENGINES_DIR = os.path.join(CCRL_ROOT, "engines")


def talk(exe, depth, timeout=120):
    p = subprocess.Popen([exe], cwd=os.path.dirname(exe), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(l.rstrip("\n")) for l in p.stdout], daemon=True).start()
    lines = []

    def send(cmd):
        p.stdin.write(cmd + "\n")
        p.stdin.flush()

    def wait_for(pattern, secs):
        end = time.time() + secs
        while time.time() < end:
            try:
                l = q.get(timeout=0.2)
            except queue.Empty:
                if p.poll() is not None:
                    return None
                continue
            lines.append(l)
            if re.match(pattern, l):
                return l
        return None

    res = {"uciok": False, "readyok": False, "bestmove": None, "depth": None, "secs": None}
    try:
        send("uci")
        res["uciok"] = wait_for(r"^uciok\b", 30) is not None
        send("isready")
        res["readyok"] = wait_for(r"^readyok\b", 60) is not None
        send("position startpos")
        t0 = time.time()
        send(f"go depth {depth}")
        bm = wait_for(r"^bestmove\b", timeout)
        res["secs"] = round(time.time() - t0, 1)
        if bm:
            res["bestmove"] = bm.split()[1] if len(bm.split()) > 1 else "?"
        depths = [int(m.group(1)) for l in lines for m in [re.search(r"\bdepth (\d+)", l)] if m]
        res["depth"] = max(depths) if depths else None
        send("quit")
        p.wait(10)
    except Exception as e:
        res["error"] = str(e)
    finally:
        if p.poll() is None:
            p.kill()
    return res, lines


def main():
    ap = argparse.ArgumentParser(description="Verifica UCI + ricerca dei motori",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("engines", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--depth", type=int, default=12)
    a = ap.parse_args()
    folders = sorted(d for d in os.listdir(ENGINES_DIR) if os.path.isdir(os.path.join(ENGINES_DIR, d))) \
        if a.all else a.engines
    if not folders:
        sys.exit("indicare i motori o --all")
    ok_all = True
    for f in folders:
        d = os.path.join(ENGINES_DIR, f)
        exes = glob.glob(os.path.join(d, "**", "*.exe"), recursive=True)
        if len(exes) != 1:
            print(f"{f:24} ERRORE: {len(exes)} eseguibili"); ok_all = False; continue
        exe = exes[0]
        sha = hashlib.sha256(open(exe, "rb").read()).hexdigest()
        res, lines = talk(exe, a.depth)
        idname = next((l[8:] for l in lines if l.startswith("id name ")), "?")
        opts = [l for l in lines if l.startswith("option name ")]
        with open(os.path.join(d, "uci_options.txt"), "w", encoding="utf-8") as fh:
            fh.write("id name " + idname + "\n" + "\n".join(opts) + "\n")
        good = res["uciok"] and res["readyok"] and res["bestmove"] not in (None, "(none)", "0000", "a1a1")
        ok_all &= good
        syz = any(o.startswith("option name SyzygyPath ") for o in opts)
        print(f"{f:24} {'OK ' if good else 'KO '} id='{idname}' | bestmove {res['bestmove']} depth {res['depth']} "
              f"in {res['secs']}s | {len(opts)} opzioni | Syzygy {'si' if syz else 'no'} | sha256 {sha[:16]}...")
        if not good:
            print("      ultime righe:", " | ".join(lines[-6:]))
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
