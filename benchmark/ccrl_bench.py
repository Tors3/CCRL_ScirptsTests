#!/usr/bin/env python3
"""
ccrl_bench.py - CCRL time control calibration using the Stockfish 10 bench.
Works on Windows and Linux (macOS without pinning). No external dependencies.

Place the script next to the Stockfish 10 folder, for example:
    ccrl_bench.py
    stockfish-10-win/Windows/stockfish_10_x64_bmi2.exe  (and the other builds)
    stockfish-10-linux/Linux/stockfish_10_x64_bmi2      (optional, for Linux)

Usage:
    python ccrl_bench.py [--ref-ms 2054]                 (fully automatic)
    python ccrl_bench.py --levels 1,4,8
    python ccrl_bench.py --sf C:\\path\\to\\stockfish_10_x64.exe

Method: N games in parallel with ponder off = roughly N cores busy, so the
N load is simulated with N single-threaded `bench` instances running at the
same time, each pinned to a different logical CPU.
factor = nps_ref / avg_nps_per_instance
"""
import argparse
import csv
import json
import os
import platform
import re
import socket
import statistics
import struct
import subprocess
import sys
import threading
from datetime import datetime

IS_WIN = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

NPS_RE = re.compile(r"Nodes/second\s*:\s*(\d+)")
NODES_RE = re.compile(r"Nodes searched\s*:\s*(\d+)")
SF10_PATH_RE = re.compile(r"stockfish[ _\-]*10", re.I)

# Official CCRL reference (after "Modernising Our lists Stage 2", Jan 2020):
# i7-4770K, SF10's default `bench` -> Total time 2054 ms, 3939338 nodes.
# T = your_time / 2054 x 15 (40/15)   |   T = your_time / 2054 x 2 (40/2)
REF_TIME_MS = 2054
REF_NODES = 3939338


# ======================================================================= CPU info
def cpu_model_vendor():
    model, vendor = platform.processor() or "?", "?"
    try:
        if IS_LINUX:
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                elif line.startswith("vendor_id"):
                    vendor = line.split(":", 1)[1].strip()
                if model != "?" and vendor != "?" and line.strip() == "":
                    break
        elif IS_WIN:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            model = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
            vendor = winreg.QueryValueEx(k, "VendorIdentifier")[0].strip()
    except Exception:
        pass
    return model, vendor


def cpu_features():
    """Returns (has_popcnt, has_bmi2). On Windows AVX2 is used as a proxy for BMI2."""
    try:
        if IS_LINUX:
            for line in open("/proc/cpuinfo"):
                if line.startswith("flags"):
                    f = set(line.split(":", 1)[1].split())
                    return "popcnt" in f, "bmi2" in f
        elif IS_WIN:
            import ctypes
            ipf = ctypes.windll.kernel32.IsProcessorFeaturePresent
            return bool(ipf(38)), bool(ipf(40))  # SSE4.2, AVX2
    except Exception:
        pass
    return False, False


# ======================================================================= topology
def topo_linux():
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = list(range(os.cpu_count() or 1))
    cpus = []
    for c in allowed:
        base = f"/sys/devices/system/cpu/cpu{c}/topology/"
        try:
            pkg = int(open(base + "physical_package_id").read())
            core = int(open(base + "core_id").read())
        except (OSError, ValueError):
            pkg, core = 0, c
        cpus.append({"id": c, "socket": pkg, "core": (pkg, core), "label": str(c)})
    return cpus


def topo_windows():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = k32.GetLogicalProcessorInformationEx
    fn.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL
    n = wintypes.DWORD(0)
    fn(0xFFFF, None, ctypes.byref(n))
    buf = ctypes.create_string_buffer(n.value)
    if not fn(0xFFFF, buf, ctypes.byref(n)):
        raise OSError(ctypes.get_last_error(), "GetLogicalProcessorInformationEx")
    raw = buf.raw[:n.value]
    ps = ctypes.sizeof(ctypes.c_void_p)          # KAFFINITY
    gsz, mfmt = (16, "<Q") if ps == 8 else (12, "<I")

    def gaff(p, cnt):
        return [(struct.unpack_from("<H", raw, p + i * gsz + ps)[0],
                 struct.unpack_from(mfmt, raw, p + i * gsz)[0]) for i in range(cnt)]

    def bits(mask):
        return [b for b in range(ps * 8) if (mask >> b) & 1]

    cores, packages, nodes = [], [], []
    off = 0
    while off + 8 <= len(raw):
        rel, size = struct.unpack_from("<II", raw, off)
        p = off + 8
        if rel in (0, 3):                         # ProcessorCore, ProcessorPackage
            gc = struct.unpack_from("<H", raw, p + 22)[0]
            (cores if rel == 0 else packages).append(gaff(p + 24, max(1, gc)))
        elif rel == 1:                            # NumaNode
            node = struct.unpack_from("<I", raw, p)[0]
            gc = struct.unpack_from("<H", raw, p + 22)[0]
            nodes.append((node, gaff(p + 24, max(1, gc))))
        if size == 0:
            break
        off += size

    sock_of, node_of = {}, {}
    for si, g in enumerate(packages):
        for grp, mask in g:
            for b in bits(mask):
                sock_of[(grp, b)] = si
    for node, g in nodes:
        for grp, mask in g:
            for rel_i, b in enumerate(bits(mask)):
                node_of[(grp, b)] = (node, rel_i)   # index relative to the NUMA node
    cpus = []
    for ci, g in enumerate(cores):
        for grp, mask in g:
            for b in bits(mask):
                cpus.append({"id": (grp, b), "socket": sock_of.get((grp, b), 0),
                             "core": ("c", ci), "label": f"G{grp}:{b}",
                             "node": node_of.get((grp, b), (0, b))})
    return cpus


def topo_generic():
    return [{"id": i, "socket": 0, "core": i, "label": str(i)}
            for i in range(os.cpu_count() or 1)]


def get_topology():
    try:
        if IS_LINUX:
            return topo_linux()
        if IS_WIN:
            return topo_windows()
    except Exception as e:
        print(f"WARNING: failed to read topology ({e}), using generic topology")
    return topo_generic()


def ordered_cpus(cpus):
    """Physical cores of socket 0, then of the following sockets, then the HT siblings."""
    by_core = {}
    for c in cpus:
        by_core.setdefault(c["core"], []).append(c)
    keys = sorted(by_core, key=lambda k: (by_core[k][0]["socket"], by_core[k][0]["id"]))
    order = [by_core[k][0] for k in keys]
    for i in range(1, max(len(v) for v in by_core.values())):
        order += [by_core[k][i] for k in keys if len(by_core[k]) > i]
    return order, len(keys)


def auto_levels(order, n_phys):
    s0 = order[0]["socket"]
    phys_s0 = sum(1 for c in order[:n_phys] if c["socket"] == s0)
    n_log = len(order)
    lv = {1, max(1, phys_s0 // 2), phys_s0, n_phys, n_log}
    if n_log > n_phys:
        lv.add((n_phys + n_log) // 2)
    return sorted(lv)


# ======================================================================= binary
def find_binaries():
    """Looks for Stockfish 10 builds in 'stockfish...10...' folders near
    the script (and in the current directory). Returns {build: path}."""
    found, others = {}, []
    for root in dict.fromkeys([SCRIPT_DIR, os.getcwd()]):
        for dirpath, dirnames, files in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth == 0:
                dirnames[:] = [d for d in dirnames if "stockfish" in d.lower()]
            elif depth >= 3:
                dirnames[:] = []
            for f in files:
                fl = f.lower()
                if not fl.startswith("stockfish"):
                    continue
                path = os.path.join(dirpath, f)
                is_exe = fl.endswith(".exe")
                if IS_WIN != is_exe or (not IS_WIN and "." in fl.replace("_x64", "")):
                    others.append(path)
                    continue
                if not SF10_PATH_RE.search(os.path.relpath(path, root)):
                    continue
                # 32-bit builds are far slower and would inflate the factor:
                # never pick them (stockfish_10_x32.exe must not pass as "x64")
                if re.search(r"x32|32bit|_32\b|win32|i386|x86(?![-_]?64)", fl):
                    others.append(path)
                    continue
                build = "bmi2" if "bmi2" in fl else "popcnt" if "popcnt" in fl else "x64"
                # prefer a name that says x64 over an ambiguous one
                if build not in found or ("x64" in fl and "x64" not in os.path.basename(found[build]).lower()):
                    found[build] = path
    return found, others


def pick_binary(args):
    if args.sf:
        return os.path.abspath(args.sf), "manual"
    found, others = find_binaries()
    if not found:
        msg = "No Stockfish 10 binary found next to the script."
        if others and not IS_WIN and any(o.lower().endswith(".exe") for o in others):
            msg += ("\nOnly the Windows version (.exe) was found: on Linux you need the "
                    "stockfish-10-linux folder (or build the sf_10 tag).")
        sys.exit(msg + "\nAlternatively, specify the path with --sf")
    has_popcnt, has_bmi2 = cpu_features()
    _, vendor = cpu_model_vendor()
    if args.build != "auto":
        if args.build not in found:
            sys.exit(f"Build '{args.build}' not found. Available: {sorted(found)}")
        return found[args.build], args.build
    # Auto: bmi2 only on Intel (on AMD Zen1/Zen2 PEXT is very slow)
    if "bmi2" in found and has_bmi2 and "Intel" in vendor:
        b = "bmi2"
    elif "popcnt" in found and has_popcnt:
        b = "popcnt"
    elif "x64" in found:
        b = "x64"
    else:
        b = sorted(found)[0]
    return found[b], b


def check_binary(sf):
    if not os.path.isfile(sf):
        sys.exit(f"File not found: {sf}")
    if not IS_WIN and not os.access(sf, os.X_OK):
        try:
            os.chmod(sf, os.stat(sf).st_mode | 0o111)
        except OSError:
            sys.exit(f"Binary is not executable: chmod +x '{sf}'")
    try:
        p = subprocess.run([sf], input="uci\nquit\n", capture_output=True,
                           text=True, timeout=20)
        m = re.search(r"id name (.+)", p.stdout)
        name = m.group(1).strip() if m else "?"
    except Exception as e:
        sys.exit(f"Unable to start {sf}: {e}")
    if not name.startswith("Stockfish 10"):
        print(f"WARNING: the engine identifies itself as '{name}', not Stockfish 10!")
    # Stockfish 10 reports its word size in the id name ("Stockfish 10 64").
    # A 32-bit build runs at roughly half the speed and would inflate the
    # factor (and so the time control), so stop instead of measuring it.
    if re.search(r"\b32\b", name) or (not re.search(r"\b64\b", name)
                                      and re.search(r"x32|32bit|win32|i386", os.path.basename(sf).lower())):
        sys.exit(f"'{name}' ({os.path.basename(sf)}) is a 32-bit build: use the 64-bit one "
                 f"(--sf path\\to\\stockfish_10_x64.exe). A 32-bit binary would inflate the factor.")
    return name


# ======================================================================= bench
class Runner:
    """pin = 'linux' (thread affinity, inherited by the child process),
             'win'   (cmd start /NODE /AFFINITY), 'none'."""

    def __init__(self, sf, hash_mb, depth, pin):
        self.sf, self.hash, self.depth, self.pin = sf, hash_mb, depth, pin

    def bench_args(self):
        return ["bench", str(self.hash), "1", str(self.depth), "default", "depth"]

    def run(self, cpu):
        if self.pin == "win":
            node, rel = cpu["node"]
            cmd = (f'cmd /d /c start "" /B /WAIT /NODE {node} /AFFINITY {1 << rel:X} '
                   f'"{self.sf}" ' + " ".join(self.bench_args()))
            p = subprocess.run(cmd, capture_output=True, text=True)
        else:
            p = subprocess.run([self.sf] + self.bench_args(),
                               capture_output=True, text=True)
        txt = p.stdout + p.stderr  # SF10 prints the summary to stderr
        m = NPS_RE.search(txt)
        if not m:
            raise RuntimeError(f"unrecognized bench output (cpu {cpu['label']}): "
                               f"{txt.strip()[-300:]}")
        n = NODES_RE.search(txt)
        return int(m.group(1)), (int(n.group(1)) if n else None)

    def enter_thread(self, cpu):
        if self.pin == "linux":
            os.sched_setaffinity(0, {cpu["id"]})  # 0 = current thread


def run_level(runner, cpulist, runs, warmup):
    """All instances start together; whoever finishes first keeps running
    'filler' runs until everyone is done, so the load stays constant."""
    n = len(cpulist)
    results = [[] for _ in range(n)]
    nodes_seen, errors = set(), []
    lock = threading.Lock()
    finished = [0]
    all_done = threading.Event()
    barrier = threading.Barrier(n)

    def worker(i, cpu):
        try:
            runner.enter_thread(cpu)
            barrier.wait()
            for _ in range(warmup):
                runner.run(cpu)
            for _ in range(runs):
                nps, nodes = runner.run(cpu)
                results[i].append(nps)
                if nodes:
                    with lock:
                        nodes_seen.add(nodes)
        except Exception as e:
            with lock:
                errors.append(str(e))
        finally:
            with lock:
                finished[0] += 1
                if finished[0] == n:
                    all_done.set()
        while not all_done.is_set():
            try:
                runner.run(cpu)
            except Exception:
                break

    ths = [threading.Thread(target=worker, args=(i, c), daemon=True)
           for i, c in enumerate(cpulist)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    return results, nodes_seen, errors


def choose_pin_mode(sf, hash_mb, first_cpu, want_pin):
    if not want_pin:
        return "none"
    if IS_LINUX and hasattr(os, "sched_setaffinity"):
        return "linux"
    if IS_WIN and "node" in first_cpu:
        r = Runner(sf, hash_mb, 1, "win")
        try:
            r.run(first_cpu)
            return "win"
        except Exception as e:
            print(f"WARNING: Windows pinning not working ({e}); "
                  f"continuing without pinning")
    return "none"


# ======================================================================= TC
def fmt_min(minutes):
    s = round(minutes * 60)
    return f"{s // 60}:{s % 60:02d}"


def time_controls(f):
    return {"40/15": f"40/{round(15 * f)}  ({fmt_min(15 * f)})",
            "40/2": f"40/{fmt_min(2 * f)}",
            "15m+10s": f"{fmt_min(15 * f)} + {10 * f:.1f}s",
            "2m+1s": f"{120 * f:.0f}s + {f:.2f}s"}


def system_checks():
    warn = []
    if IS_LINUX:
        gov = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        if os.path.exists(gov):
            g = open(gov).read().strip()
            if g != "performance":
                warn.append(f"governor '{g}' (recommended: sudo cpupower "
                            f"frequency-set -g performance)")
        la = os.getloadavg()[0]
        if la > 1.0:
            warn.append(f"load average {la:.2f}: close other processes")
    elif IS_WIN:
        try:
            out = subprocess.run(["powercfg", "/getactivescheme"],
                                 capture_output=True, text=True).stdout.lower()
            known = any(g in out for g in ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
                                           "e9a42b02-d5df-448d-aa00-03f14749eb61"))
            # A custom or OEM plan (a duplicate of High performance, any language)
            # has its own GUID, so check what actually matters instead: the
            # minimum processor state on AC. 100% means the CPU never downclocks.
            if not known:
                q = subprocess.run(["powercfg", "/query", "SCHEME_CURRENT",
                                    "SUB_PROCESSOR", "PROCTHROTTLEMIN"],
                                   capture_output=True, text=True).stdout
                ac = re.findall(r":\s*0x([0-9a-fA-F]+)", q)
                # the last two values are the current AC and DC indices
                min_state = int(ac[-2], 16) if len(ac) >= 2 else None
                if min_state is None:
                    warn.append("could not read the power plan: make sure the "
                                "minimum processor state is 100% "
                                "(powercfg /setactive SCHEME_MIN)")
                elif min_state < 100:
                    warn.append(f"minimum processor state is {min_state}% on AC: "
                                f"the CPU can downclock during the benchmark "
                                f"(powercfg /setactive SCHEME_MIN)")
        except Exception:
            pass
    return warn


# ======================================================================= main
def main():
    ap = argparse.ArgumentParser(description="CCRL benchmark with Stockfish 10")
    ap.add_argument("--sf", help="path to the binary (default: automatic search)")
    ap.add_argument("--build", default="x64", choices=["auto", "x64", "popcnt", "bmi2"])
    ap.add_argument("--levels", default="auto",
                    help="concurrent instances, e.g. 1,10,20,40,60,80 (default: auto)")
    ap.add_argument("--runs", type=int, default=5, help="measured runs per instance")
    ap.add_argument("--warmup", type=int, default=1, help="discarded warmup runs")
    ap.add_argument("--hash", type=int, default=16, help="hash MB (bench default)")
    ap.add_argument("--depth", type=int, default=13, help="depth (SF10 default: 13)")
    ap.add_argument("--ref-ms", type=float, default=REF_TIME_MS,
                    help=f"i7-4770K reference bench time in ms (default {REF_TIME_MS})")
    ap.add_argument("--no-pin", action="store_true", help="do not pin instances to CPUs")
    ap.add_argument("--out", help="output file prefix")
    args = ap.parse_args()

    sf, build = pick_binary(args)
    engine_name = check_binary(sf)

    cpus = get_topology()
    order, n_phys = ordered_cpus(cpus)
    n_sock = len({c["socket"] for c in cpus})
    if args.levels == "auto":
        levels = auto_levels(order, n_phys)
    else:
        levels = [int(x) for x in args.levels.split(",") if x.strip()]
    too_big = [l for l in levels if l > len(order)]
    levels = [l for l in levels if 1 <= l <= len(order)]
    pin = choose_pin_mode(sf, args.hash, order[0], not args.no_pin)
    model, _ = cpu_model_vendor()

    print(f"Host      : {socket.gethostname()} ({platform.system()} {platform.release()})")
    print(f"CPU       : {model}")
    print(f"Topology  : {n_sock} socket(s), {n_phys} physical cores, {len(order)} logical CPUs")
    print(f"Engine    : {engine_name}  [build {build}]")
    print(f"Binary    : {sf}")
    print(f"Pinning   : {pin}")
    print(f"Reference : i7-4770K, {args.ref_ms:.0f} ms ({REF_NODES:,} nodes)")
    print(f"Levels    : {levels} | runs={args.runs} warmup={args.warmup} "
          f"hash={args.hash}MB depth={args.depth}")
    if too_big:
        print(f"WARNING: levels ignored because > logical CPUs: {too_big}")
    for w in system_checks():
        print(f"WARNING: {w}")
    print()

    runner = Runner(sf, args.hash, args.depth, pin)
    rows, signatures = [], set()
    for lvl in levels:
        cpulist = order[:lvl]
        n_ht = max(0, lvl - n_phys)
        socks = sorted({c["socket"] for c in cpulist})
        print(f"== {lvl} instances | socket {socks} | HT siblings used: {n_ht}", flush=True)
        t0 = datetime.now()
        results, nodes, errors = run_level(runner, cpulist, args.runs, args.warmup)
        dt = (datetime.now() - t0).total_seconds()
        for e in errors[:3]:
            print(f"   ERROR: {e}")
        samples = [x for r in results for x in r]
        if not samples:
            print("   no valid samples, skipping\n")
            continue
        signatures |= nodes
        per_inst = [statistics.mean(r) for r in results if r]
        mean = statistics.mean(samples)
        row = {"instances": lvl, "sockets": "+".join(map(str, socks)),
               "ht_siblings": n_ht, "nps_mean": round(mean),
               "nps_median": round(statistics.median(samples)),
               "nps_min_instance": round(min(per_inst)),
               "nps_max_instance": round(max(per_inst)),
               "stdev_pct": round(100 * statistics.pstdev(samples) / mean, 2),
               "total_nps": round(mean * lvl), "seconds": round(dt, 1)}
        print(f"   nps/instance: mean {row['nps_mean']:,}  median {row['nps_median']:,}  "
              f"min {row['nps_min_instance']:,}  max {row['nps_max_instance']:,}  "
              f"(sd {row['stdev_pct']}%)  [{dt:.0f}s]")
        # equivalent time of the standard bench: fixed nodes / measured nps
        t_ms = REF_NODES / mean * 1000
        f = t_ms / args.ref_ms
        tcs = time_controls(f)
        row["bench_time_ms"] = round(t_ms)
        row["factor"] = round(f, 4)
        row.update({f"tc_{k}": v for k, v in tcs.items()})
        print(f"   equiv. bench time {t_ms:.0f} ms -> factor {f:.3f} | "
              f"40/15: {tcs['40/15']} | 40/2: {tcs['40/2']} | "
              f"15+10: {tcs['15m+10s']} | 2+1: {tcs['2m+1s']}")
        print()
        rows.append(row)

    if not rows:
        sys.exit("No results.")

    base = rows[0]["nps_mean"]
    print("=" * 80)
    hdr = (f"{'inst.':>5} {'socket':>7} {'HT':>4} {'nps/inst':>12} {'vs 1st':>7} "
           f"{'tot Mnps':>9} {'bench ms':>9} {'factor':>8} {'40/15':>14} {'2+1':>12}")
    print(hdr)
    for r in rows:
        line = (f"{r['instances']:>5} {r['sockets']:>7} {r['ht_siblings']:>4} "
                f"{r['nps_mean']:>12,} {100 * r['nps_mean'] / base:>6.1f}% "
                f"{r['total_nps'] / 1e6:>9.2f}")
        line += (f" {r['bench_time_ms']:>9} {r['factor']:>8.3f} "
                 f"{r['tc_40/15']:>14} {r['tc_2m+1s']:>12}")
        print(line)
    if signatures:
        std = args.hash == 16 and args.depth == 13
        ok = signatures == {REF_NODES}
        print(f"\nNodes searched: {sorted(signatures)}  (expected {REF_NODES:,})  "
              + ("OK" if ok else "<-- MISMATCH: different binary or parameters, "
                 "result NOT valid for CCRL" if std else
                 "(non-standard hash/depth: CCRL comparison not valid)"))

    host = re.sub(r"[^\w\-]", "_", socket.gethostname())
    prefix = args.out or os.path.join(
        SCRIPT_DIR, f"ccrl_bench_{host}_{datetime.now():%Y%m%d_%H%M%S}")
    with open(prefix + ".csv", "w", newline="") as fh:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(prefix + ".json", "w") as fh:
        json.dump({"host": socket.gethostname(), "os": platform.platform(),
                   "cpu": model, "engine": engine_name, "build": build, "sf": sf,
                   "pin": pin, "args": vars(args), "signature": sorted(signatures),
                   "results": rows}, fh, indent=2)
    print(f"\nSaved: {prefix}.csv / .json")


if __name__ == "__main__":
    main()