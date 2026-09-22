#!/usr/bin/env python3
"""
run_node.py - driver di un'istanza del gauntlet CCRL (un nodo NUMA).

Lanciato da gauntlet.bat (che imposta i parametri come variabili d'ambiente)
tramite  start /NODE n /AFFINITY <mask>, cosi' fastchess e tutti i motori
figli ereditano nodo e maschera di affinita'. In piu' il driver si mette in un
Job Object con lo stesso limite (vedi apply_job_affinity).

Perche' non "-tournament gauntlet" di fastchess:
  * in modalita' gauntlet fastchess tronca il libro a -rounds aperture
    (OpeningBook::setup -> truncate(rounds)): con 10 round userebbe 10 aperture
    ripetute contro tutti gli avversari;
  * "-config file=" (ripresa) scarta le statistiche se ci sono piu' di 2 motori
    ("Stats will be dropped for more than 2 engines"): non si potrebbe riprendere.
Quindi ogni istanza gioca una sequenza di match a 2 motori (seed vs avversario),
in PASSES passate da ROUNDS_PER_PASS aperture ciascuna, con un offset di
aperture diverso per ogni (nodo, passata, avversario): nessuna apertura si ripete.
Ogni match ha il proprio <name>.json (stato fastchess) e puo' essere ripreso.

Variabili d'ambiente (tutte con default, vedi gauntlet.bat):
  GAUNTLET_DIR, NODE, HASH, THREADS, TC, CONCURRENCY, PASSES, ROUNDS_PER_PASS,
  BOOK, BOOK_START, LOG_LEVEL, EVENT, SITE, FASTCHESS, EXTRA_ARGS, SYZYGY_PATH,
  OPP_FILTER, MODE, AFFINITY_MASK, DRY_RUN
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CCRL_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))


def env(name, default):
    v = os.environ.get(name, "").strip()
    return v if v else default


GAUNTLET_DIR = os.path.abspath(env("GAUNTLET_DIR", os.path.join(SCRIPT_DIR, "..")))
NODE = int(env("NODE", "0"))
HASH = env("HASH", "2048")
THREADS = env("THREADS", "4")
TC = env("TC", "1690+19")
CONCURRENCY = env("CONCURRENCY", "5")
PASSES = int(env("PASSES", "2"))
ROUNDS_PER_PASS = int(env("ROUNDS_PER_PASS", "5"))
BOOK = env("BOOK", os.path.join(CCRL_ROOT, "books", "avt-book-2026.pgn"))
BOOK_START = int(env("BOOK_START", "1"))
LOG_LEVEL = env("LOG_LEVEL", "info")
EVENT = env("EVENT", "CCRL 40/15 gauntlet")
SITE = env("SITE", "Xeon-Server")
FASTCHESS = env("FASTCHESS", os.path.join(CCRL_ROOT, "tools", "fastchess", "fastchess.exe"))
EXTRA_ARGS = env("EXTRA_ARGS", "")          # aggiudicazioni / -tb di fastchess (vedi gauntlet.bat)
SYZYGY_PATH = env("SYZYGY_PATH", "")        # se impostato: option.SyzygyPath ai motori che la supportano
OPP_FILTER = env("OPP_FILTER", "")          # es. "1-10" o "3,7": sottoinsieme di accoppiamenti (1-based)
MODE = env("MODE", "gauntlet").lower()     # gauntlet: seed vs tutti | roundrobin: tutti contro tutti
AFFINITY_MASK = env("AFFINITY_MASK", "0x5555555555")  # mask relativa al nodo; "" o "0" = nessun Job Object
ENGINES_JSON = env("ENGINES_JSON", os.path.join(GAUNTLET_DIR, "config", "engines.json"))
DRY_RUN = env("DRY_RUN", "0") == "1"

PGN_DIR = os.path.join(GAUNTLET_DIR, "pgn")
LOG_DIR = os.path.join(GAUNTLET_DIR, "logs")
PGN_FILE = os.path.join(PGN_DIR, f"node{NODE}.pgn")
GAMES_DIR = os.path.join(PGN_DIR, "games")     # una partita per file (estratte dal PGN del nodo)
DRIVER_LOG = os.path.join(LOG_DIR, f"node{NODE}_driver.log")


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] node{NODE}: {msg}"
    print(line, flush=True)
    with open(DRIVER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def slug(name):
    return re.sub(r"[^A-Za-z0-9.\-]+", "_", name)


def supports_option(e, opt):
    """Legge engines/<folder>/uci_options.txt (salvato durante la verifica dei motori)."""
    p = os.path.join(CCRL_ROOT, "engines", e["folder"], "uci_options.txt")
    try:
        return re.search(rf"^option name {re.escape(opt)} type", open(p, encoding="utf-8").read(), re.M) is not None
    except OSError:
        return False


def engine_args(e):
    args = ["-engine", f"cmd={e['cmd']}", f"name={e['name']}", f"dir={e['dir']}"]
    for k, v in e.get("options", {}).items():
        v = str(v).replace("${THREADS}", THREADS).replace("${HASH}", HASH)
        args.append(f"option.{k}={v}")
    if SYZYGY_PATH and supports_option(e, "SyzygyPath"):
        args.append(f"option.SyzygyPath={SYZYGY_PATH}")
    return args


def parse_filter(spec, n):
    """"1-10" / "3,7,12" -> insieme di indici 0-based."""
    sel = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            sel.update(range(int(a) - 1, int(b)))
        else:
            sel.add(int(part) - 1)
    return {i for i in sel if 0 <= i < n}


def count_games_in_pgn(path, event, name_a, name_b):
    """Partite gia' concluse fra name_a e name_b con quel tag Event nel PGN di questo nodo."""
    if not os.path.exists(path):
        return 0
    n = 0
    cur = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.match(r'\[(\w+) "(.*)"\]', line)
            if m:
                cur[m.group(1)] = m.group(2)
            elif line.strip() and not line.startswith("["):
                # prima riga di mosse -> intestazione completa
                if cur:
                    if (cur.get("Event") == event and cur.get("Result") in ("1-0", "0-1", "1/2-1/2")
                            and {cur.get("White"), cur.get("Black")} == {name_a, name_b}):
                        n += 1
                    cur = {}
    return n


def split_pgn_games(src, out_dir, prefix):
    """Esporta ogni partita conclusa di `src` in un file separato
    <prefix>_<nnnn>_<Bianco>_vs_<Nero>.pgn (nnnn = posizione nel PGN del nodo).
    fastchess sa scrivere solo un file per run (-pgnout file=), quindi la
    suddivisione per partita viene fatta qui. Idempotente: i file gia' presenti
    non vengono riscritti; una partita e' considerata completa solo se il
    movetext termina con il risultato."""
    if not os.path.exists(src):
        return 0
    os.makedirs(out_dir, exist_ok=True)
    text = open(src, encoding="utf-8", errors="replace").read()
    written = 0
    n = 0
    for block in re.split(r"\n\s*\n(?=\[)", text):
        block = block.strip("\n")
        if not block.startswith("["):
            continue
        n += 1
        hdr = dict(re.findall(r'^\[(\w+) "(.*)"\]', block, re.M))
        result = hdr.get("Result", "*")
        if result == "*" or not block.rstrip().endswith(result):
            continue
        name = f"{prefix}_{n:04d}_{slug(hdr.get('White', '?'))}_vs_{slug(hdr.get('Black', '?'))}.pgn"
        dst = os.path.join(out_dir, name)
        if os.path.exists(dst):
            continue
        tmp = dst + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(block + "\n\n")
        os.replace(tmp, dst)
        written += 1
    return written


def start_pgn_splitter(interval=30):
    """Thread in background: ogni `interval` secondi esporta le nuove partite concluse."""
    def loop():
        while True:
            try:
                split_pgn_games(PGN_FILE, GAMES_DIR, f"node{NODE}")
            except Exception as e:  # mai fermare il gauntlet per un errore di export
                log(f"ATTENZIONE: split PGN fallito: {e}")
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def apply_job_affinity(group, mask):
    """Mette il driver (e quindi fastchess e tutti i motori figli) in un Job Object
    con limite di gruppo NUMA + affinity. Serve perche' alcuni motori (Caissa 2.0:
    Search.cpp, PinCurrentThreadToNumaNode) impostano da soli l'affinity dei propri
    thread su TUTTI i nodi NUMA, ignorando la mask ereditata da "start /AFFINITY".
    Il limite del Job Object invece non e' aggirabile dal processo figlio."""
    import ctypes
    from ctypes import wintypes

    class GROUP_AFFINITY(ctypes.Structure):
        _fields_ = [("Mask", ctypes.c_size_t), ("Group", wintypes.WORD), ("Reserved", wintypes.WORD * 3)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)
    ga = GROUP_AFFINITY(mask, group)
    JobObjectGroupInformationEx = 14
    if not k.SetInformationJobObject(job, JobObjectGroupInformationEx, ctypes.byref(ga), ctypes.sizeof(ga)):
        return f"SetInformationJobObject fallita (err {ctypes.get_last_error()})"
    if not k.AssignProcessToJobObject(job, k.GetCurrentProcess()):
        return f"AssignProcessToJobObject fallita (err {ctypes.get_last_error()})"
    return None


def run(cmd, cwd):
    log("CMD: " + subprocess.list2cmdline(cmd))
    if DRY_RUN:
        return 0
    t0 = time.time()
    rc = subprocess.call(cmd, cwd=cwd)
    log(f"fastchess exit code {rc} after {time.time() - t0:.0f}s")
    return rc


def main():
    os.makedirs(PGN_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    for p in (FASTCHESS, BOOK, ENGINES_JSON):
        if not os.path.exists(p):
            sys.exit(f"ERRORE: file non trovato: {p}")
    cfg = json.load(open(ENGINES_JSON, encoding="utf-8"))
    seed, opponents = cfg["seed"], cfg["opponents"]
    for e in [seed] + opponents:
        if not os.path.exists(e["cmd"]):
            sys.exit(f"ERRORE: motore mancante: {e['name']} -> {e['cmd']}")

    if MODE == "roundrobin":
        allp = [seed] + opponents
        pairings = [(allp[i], allp[k]) for i in range(len(allp)) for k in range(i + 1, len(allp))]
    elif MODE == "gauntlet":
        pairings = [(seed, o) for o in opponents]
    else:
        sys.exit(f"ERRORE: MODE={MODE} non valido (gauntlet|roundrobin)")
    n_pair = len(pairings)
    games_per_match = 2 * ROUNDS_PER_PASS

    if os.name == "nt" and AFFINITY_MASK and int(AFFINITY_MASK, 16) != 0:
        err = apply_job_affinity(NODE, int(AFFINITY_MASK, 16))
        if err:
            log(f"ATTENZIONE: Job Object affinity non applicato: {err}")
        else:
            log(f"Job Object: gruppo NUMA {NODE}, mask {AFFINITY_MASK} (vincola anche i motori che si auto-pinnano)")

    log(f"start | mode={MODE} | seed={seed['name']} | {n_pair} accoppiamenti | passes={PASSES} rounds/pass={ROUNDS_PER_PASS} "
        f"({PASSES * games_per_match} partite/accoppiamento su questo nodo) | tc={TC} threads={THREADS} hash={HASH} "
        f"concurrency={CONCURRENCY} | book={os.path.basename(BOOK)} | syzygy='{SYZYGY_PATH}' | extra='{EXTRA_ARGS}'")

    total_done = total_played_now = 0
    if not DRY_RUN:
        start_pgn_splitter()
    selected = parse_filter(OPP_FILTER, n_pair) if OPP_FILTER else set(range(n_pair))
    if OPP_FILTER:
        log(f"OPP_FILTER={OPP_FILTER} -> accoppiamenti {sorted(i + 1 for i in selected)}")
    for p in range(1, PASSES + 1):
        for j, (ea, eb) in enumerate(pairings):
            if j not in selected:
                continue
            # offset aperture: nodo -> passata -> accoppiamento, blocchi disgiunti di ROUNDS_PER_PASS aperture
            block = (NODE * PASSES + (p - 1)) * n_pair + j
            start = BOOK_START + block * ROUNDS_PER_PASS
            event = f"{EVENT} node{NODE} pass{p}"
            label = f"{ea['name']} vs {eb['name']}"
            tag = f"node{NODE}_p{p}_{slug(ea['name'])}_vs_{slug(eb['name'])}"
            cfg_json = os.path.join(LOG_DIR, tag + ".json")
            log_file = os.path.join(LOG_DIR, tag + ".log")

            done = count_games_in_pgn(PGN_FILE, event, ea["name"], eb["name"])
            if done >= games_per_match:
                log(f"pass {p} {label}: gia' completo ({done}/{games_per_match}), salto")
                total_done += done
                continue

            if os.path.exists(cfg_json) and done > 0:
                log(f"pass {p} {label}: RIPRESA da {done}/{games_per_match} partite ({os.path.basename(cfg_json)})")
                cmd = [FASTCHESS, "-config", f"file={cfg_json}"]
            else:
                log(f"pass {p} {label}: nuovo match, aperture {start}-{start + ROUNDS_PER_PASS - 1}")
                cmd = [FASTCHESS]
                cmd += engine_args(ea) + engine_args(eb)
                cmd += ["-each", f"tc={TC}", "proto=uci",
                        "-openings", f"file={BOOK}", "format=pgn", "order=sequential", f"start={start}",
                        "-rounds", str(ROUNDS_PER_PASS), "-games", "2", "-repeat",
                        "-concurrency", CONCURRENCY,
                        "-recover",
                        "-autosaveinterval", "1",
                        "-ratinginterval", "2",
                        "-event", event, "-site", SITE,
                        "-pgnout", f"file={PGN_FILE}", "notation=san", "append=true",
                        "nodes=true", "nps=true", "seldepth=true", "timeleft=true",
                        "-log", f"file={log_file}", f"level={LOG_LEVEL}", "engine=true", "append=true",
                        "-config", f"outname={cfg_json}",
                        "-startup-ms", "60000"]
                if EXTRA_ARGS:
                    cmd += EXTRA_ARGS.split()
            rc = run(cmd, GAUNTLET_DIR)
            after = count_games_in_pgn(PGN_FILE, event, ea["name"], eb["name"])
            total_played_now += after - done
            total_done += after
            if rc != 0:
                log(f"ATTENZIONE: fastchess terminato con codice {rc} (pass {p} {label}, {after}/{games_per_match} partite)")
            if after < games_per_match and not DRY_RUN:
                log(f"match incompleto ({after}/{games_per_match}); rilanciare start_node{NODE}.bat per riprendere")
    if not DRY_RUN:
        split_pgn_games(PGN_FILE, GAMES_DIR, f"node{NODE}")
    log(f"FINE | partite totali su questo nodo: {total_done} (giocate in questa sessione: {total_played_now})")


if __name__ == "__main__":
    main()
