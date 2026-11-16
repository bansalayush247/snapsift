"""Move duplicate ORIGINALS to the Trash (Mac). The only script that touches your originals, and only
when you confirm in the dashboard.

  python scripts/trash_dupes.py --list [--near]        # what would go, nothing changes
  python scripts/trash_dupes.py --confirm N [--near]   # move them; N must match the --list count

Safety:
  - only extra copies, never the copy that is kept
  - identical copies by default; --near adds look-alikes (bursts, re-saved screenshots), which are
    different files, so check them first
  - each file is checked again right before: still there, unchanged since the scan (same sha256), its kept
    copy still exists (and for identical copies is still byte-identical), and it is inside the photos folder
  - Finder moves them to the Trash, so "Put Back" works until you empty it; work/trashed.csv lists them
Deleting copies from a Google Takeout export does not free space in Google Photos: use the delete lists.
"""
import argparse, csv, hashlib, json, os, shutil, subprocess, sys, time

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, WORK, inside, load, progress, save

FINDER = """
on run argv
  set l to {}
  repeat with p in argv
    set end of l to (POSIX file (contents of p)) as alias
  end repeat
  tell application "Finder" to delete l
end run
"""


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def close_to_keeper(r, k, bits=4):
    """Look-alike groups are chained (A~B, B~C), so C may look nothing like A. Only trash a look-alike
    that is itself within `bits` of the photo that is kept."""
    try:
        return r["kind"] == k["kind"] and bin(int(r["phash"], 16) ^ int(k["phash"], 16)).count("1") <= bits
    except (KeyError, TypeError, ValueError):
        return False


def candidates(near):
    src = load(os.path.join(DATA, "source.json"), {}).get("source")
    recs = {r["id"]: r for r in load(os.path.join(DATA, "inventory.json"), [])}
    out = []
    for g in load(os.path.join(DATA, "dupes.json"), []):
        if g["type"] != "exact" and not near:
            continue
        k = recs.get(g["keep"])
        for d in g["dupes"]:
            r = recs.get(d)
            if r and k and src and inside(r["path"], src) and os.path.isfile(r["path"]) and os.path.isfile(k["path"]) \
                    and os.path.realpath(r["path"]) != os.path.realpath(k["path"]) \
                    and (g["type"] == "exact" or close_to_keeper(r, k)):
                out.append((r, k, g["type"]))
    return out


def verify(r, k, kind):
    if os.path.islink(r["path"]) or sha(r["path"]) != r["sha256"]:
        return "changed since the scan"
    if not os.path.isfile(k["path"]):
        return "its kept copy is gone"
    if kind == "exact" and sha(k["path"]) != r["sha256"]:
        return "its kept copy is no longer identical"
    return None


def to_trash(paths):
    test_dir = os.environ.get("SNAPSIFT_TRASH_DIR")  # tests only: never the real Trash
    if test_dir:
        os.makedirs(test_dir, exist_ok=True)
        for p in paths:
            shutil.move(p, os.path.join(test_dir, f"{time.time_ns()}_{os.path.basename(p)}"))
        return
    if sys.platform != "darwin":
        raise RuntimeError("Moving to the Trash only works on a Mac. Use duplicates.csv to delete them yourself.")
    r = subprocess.run(["osascript", "-e", FINDER] + paths, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        err = r.stderr.strip()
        if "-1743" in err or "not allowed" in err.lower():
            raise RuntimeError("macOS blocked access to Finder. Allow it in System Settings > Privacy & Security > Automation.")
        raise RuntimeError(err[:200])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--near", action="store_true")
    ap.add_argument("--confirm", type=int)
    a = ap.parse_args(argv)
    cands = candidates(a.near)
    if a.list or a.confirm is None:
        print(json.dumps({"files": len(cands), "bytes": sum(r["bytes"] for r, _, _ in cands), "ids": [r["id"] for r, _, _ in cands],
                          "exact": sum(t == "exact" for _, _, t in cands), "near": sum(t != "exact" for _, _, t in cands)}))
        return
    if a.confirm != len(cands):
        sys.exit(f"The list changed ({len(cands)} files now, you confirmed {a.confirm}). Look at it again first.")
    log = os.path.join(WORK, "trashed.csv")
    new_log = not os.path.exists(log)
    os.makedirs(WORK, exist_ok=True)
    moved, skipped = [], []
    with open(log, "a", newline="") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["when", "trashed", "kept", "match"])
        for s in range(0, len(cands), 100):
            ok = []
            for r, k, kind in cands[s:s + 100]:
                why = verify(r, k, kind)
                if why:
                    skipped.append(f"{r['name']}: {why}")
                else:
                    ok.append((r, k, kind))
            if ok:
                to_trash([r["path"] for r, _, _ in ok])
                for r, k, kind in ok:
                    w.writerow([time.strftime("%Y-%m-%d %H:%M"), r["path"], k["path"], kind])
                    moved.append(r["id"])
            progress(min(s + 100, len(cands)), len(cands))
    done = load(os.path.join(DATA, "trashed.json"), [])
    save(os.path.join(DATA, "trashed.json"), sorted(set(done) | set(moved)))
    print(f"Moved {len(moved)} duplicate files to the Trash (Put Back works until you empty it). List: {log}"
          + (f". Skipped {len(skipped)}: {skipped[0]}" if skipped else ""), flush=True)


if __name__ == "__main__":
    main()
