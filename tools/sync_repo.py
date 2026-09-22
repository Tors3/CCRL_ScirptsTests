#!/usr/bin/env python3
r"""
sync_repo.py - sincronizza CCRL\ con la cartella del repository GitHub.

Copia nel repo (default C:\Users\Francesco\Documents\GitHub\CCRL_Scirpts):

  bench\*.py, *.csv, *.json        -> benchmark\ e benchmark\results\
  engines\REPORT.md                -> engines\REPORT.md
  engines\<motore>\uci_options.txt -> engines\uci_options\<motore>.txt
  tools\gauntlet_template\scripts\ -> tools\gauntlet_template\scripts\
  new_gauntlet.py, sync_repo.py    -> tools\
  gauntlets\<nome>\scripts,config  -> tournaments\<nome>\scripts,config
  gauntlets\<nome>\results         -> results\gauntlets\<nome>\
  gauntlets\<nome>\pgn\node*.pgn   -> results\gauntlets\<nome>\pgn\   (--no-pgn per saltarli)

NON copia: eseguibili, reti NNUE, tablebase, log di fastchess (~1 GB per torneo;
--logs li include comunque) e i PGN per singola partita in pgn\games\ (--games-pgn
li include: sono le stesse partite dei PGN per nodo, una per file).

Uso (dalla cartella CCRL):

  python sync_repo.py                 sincronizza tutto (rigenerando i risultati)
  python sync_repo.py --no-merge      non rilancia merge_results prima di copiare
  python sync_repo.py --only 2026-09-22_Caissa_2.0_4CPU
  python sync_repo.py --dry-run       mostra solo cosa verrebbe copiato
  python sync_repo.py --commit "messaggio"      copia, git add -A e commit
  python sync_repo.py --commit "messaggio" --push

Il commit e il push avvengono solo se richiesti esplicitamente.
"""
import argparse
import filecmp
import glob
import os
import shutil
import subprocess
import sys

CCRL_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = r"C:\Users\Francesco\Documents\GitHub\CCRL_Scirpts"

copied = skipped = 0


def copy(src, dst, dry):
    """Copia src in dst se assente o diverso. Ritorna True se ha copiato."""
    global copied, skipped
    if not os.path.exists(src):
        return False
    if os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False):
        skipped += 1
        return False
    print(f"  {'[dry] ' if dry else ''}{os.path.relpath(dst, REPO)}")
    if not dry:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    copied += 1
    return True


def copy_glob(pattern, dst_dir, dry, recursive=False):
    for f in sorted(glob.glob(pattern, recursive=recursive)):
        if os.path.isfile(f):
            copy(f, os.path.join(dst_dir, os.path.basename(f)), dry)


def copy_tree(src_dir, dst_dir, dry, skip_names=()):
    if not os.path.isdir(src_dir):
        return
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in skip_names]
        for f in files:
            if f in skip_names or f.endswith(".tmp"):
                continue
            s = os.path.join(root, f)
            copy(s, os.path.join(dst_dir, os.path.relpath(s, src_dir)), dry)


def run_merge(gdir):
    """Rigenera results\\summary.md e results.csv se ci sono partite."""
    script = os.path.join(gdir, "scripts", "merge_results.py")
    if not os.path.exists(script) or not glob.glob(os.path.join(gdir, "pgn", "node*.pgn")):
        return
    r = subprocess.run([sys.executable, script, "--gauntlet-dir", gdir],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ATTENZIONE: merge_results fallito per {os.path.basename(gdir)}: "
              f"{(r.stderr or r.stdout).strip().splitlines()[-1:]}")


def main():
    global REPO
    p = argparse.ArgumentParser(description="Sincronizza CCRL con il repo GitHub",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--repo", default=DEFAULT_REPO, help=f"cartella del repo (default {DEFAULT_REPO})")
    p.add_argument("--only", help="sincronizza solo questo gauntlet (nome della cartella)")
    p.add_argument("--no-merge", action="store_true", help="non rigenerare i risultati prima di copiare")
    p.add_argument("--no-pgn", action="store_true", help="non copiare i PGN")
    p.add_argument("--games-pgn", action="store_true", help="copia anche pgn\\games\\ (una partita per file)")
    p.add_argument("--logs", action="store_true", help="copia anche i log di fastchess (molto grandi)")
    p.add_argument("--dry-run", action="store_true", help="mostra cosa verrebbe copiato, senza copiare")
    p.add_argument("--commit", metavar="MSG", help="dopo la copia esegue git add -A e git commit -m MSG")
    p.add_argument("--push", action="store_true", help="con --commit, esegue anche git push")
    a = p.parse_args()
    REPO = os.path.abspath(a.repo)
    dry = a.dry_run
    if not os.path.isdir(REPO):
        sys.exit(f"ERRORE: cartella del repo non trovata: {REPO}")

    print(f"CCRL : {CCRL_ROOT}\nrepo : {REPO}\n")

    print("benchmark:")
    copy_glob(os.path.join(CCRL_ROOT, "bench", "*.py"), os.path.join(REPO, "benchmark"), dry)
    for ext in ("csv", "json"):
        copy_glob(os.path.join(CCRL_ROOT, "bench", f"*.{ext}"),
                  os.path.join(REPO, "benchmark", "results"), dry)

    print("motori:")
    copy(os.path.join(CCRL_ROOT, "engines", "REPORT.md"),
         os.path.join(REPO, "engines", "REPORT.md"), dry)
    for f in sorted(glob.glob(os.path.join(CCRL_ROOT, "engines", "*", "uci_options.txt"))):
        engine = os.path.basename(os.path.dirname(f))
        copy(f, os.path.join(REPO, "engines", "uci_options", engine + ".txt"), dry)

    print("strumenti:")
    copy_tree(os.path.join(CCRL_ROOT, "tools", "gauntlet_template"),
              os.path.join(REPO, "tools", "gauntlet_template"), dry)
    for f in ("new_gauntlet.py", "sync_repo.py"):
        copy(os.path.join(CCRL_ROOT, f), os.path.join(REPO, "tools", f), dry)

    gauntlets = sorted(d for d in glob.glob(os.path.join(CCRL_ROOT, "gauntlets", "*"))
                       if os.path.isdir(d) and not os.path.basename(d).startswith("_"))
    if a.only:
        gauntlets = [d for d in gauntlets if os.path.basename(d) == a.only]
        if not gauntlets:
            sys.exit(f"ERRORE: gauntlet '{a.only}' non trovato in gauntlets\\")

    for gdir in gauntlets:
        name = os.path.basename(gdir)
        print(f"gauntlet {name}:")
        if not a.no_merge and not dry:
            run_merge(gdir)
        copy_tree(os.path.join(gdir, "scripts"),
                  os.path.join(REPO, "tournaments", name, "scripts"), dry, skip_names=("__pycache__",))
        copy_tree(os.path.join(gdir, "config"),
                  os.path.join(REPO, "tournaments", name, "config"), dry)
        res_dst = os.path.join(REPO, "results", "gauntlets", name)
        copy_tree(os.path.join(gdir, "results"), res_dst, dry)
        if not a.no_pgn:
            copy_glob(os.path.join(gdir, "pgn", "node*.pgn"), os.path.join(res_dst, "pgn"), dry)
            if a.games_pgn:
                copy_tree(os.path.join(gdir, "pgn", "games"), os.path.join(res_dst, "pgn", "games"), dry)
        if a.logs:
            copy_tree(os.path.join(gdir, "logs"), os.path.join(res_dst, "logs"), dry)

    print(f"\n{copied} file copiati, {skipped} gia' aggiornati.")

    if a.commit and not dry:
        subprocess.run(["git", "add", "-A"], cwd=REPO, check=True)
        r = subprocess.run(["git", "commit", "-m", a.commit], cwd=REPO, capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if a.push and r.returncode == 0:
            r = subprocess.run(["git", "push"], cwd=REPO, capture_output=True, text=True)
            print(r.stdout.strip() or r.stderr.strip())
    elif a.commit and dry:
        print(f"[dry] git add -A && git commit -m \"{a.commit}\"" + (" && git push" if a.push else ""))


if __name__ == "__main__":
    main()
