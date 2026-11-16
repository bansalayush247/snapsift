"""Step 4: build the folders.  python scripts/apply.py "/where/to/put/Sorted"

Reads labels from work/labels/*.json (Claude) and/or work/jev.json (Jev).
If both exist: Jev's answer wins when it is >= 70% confident, otherwise Claude's.
COPIES files into <output>/<Folder>/ (optionally <Folder>/<year>/ or <Folder>/<year-month>/), and
files that need a look into <output>/_Review/: Duplicates, Private, Junk, Not sure.
Trips and events also get album folders in <output>/Albums/.
On a Mac (same disk) copies are APFS clones: instant and they take no extra space.

Fix dates: Google Takeout often loses the "date taken" from the file itself, so re-uploaded photos land
on the download date. The copies get the real date back (file date, and EXIF for JPEGs that have none).
Originals are never moved, renamed or changed. Also writes sorted.csv and duplicates.csv.
"""
import csv, os, shutil, subprocess, sys, time

sys.path.insert(0, os.path.dirname(__file__))
from common import (CATEGORIES, DATA, JEV_OUT, OVERRIDES, REVIEW, categories, folder_name, inside, load, options,
                    progress, read_labels, safe_name, save)

DARK = 12  # brightness (0-255) below this is junk even if Claude didn't say so


def blur_limit(recs):
    """Very blurry = under a quarter of this library's typical sharpness (JPEG noise keeps even blurry
    photos above zero, and phones differ, so a fixed number doesn't work). At least 4."""
    vals = sorted(r["sharp"] for r in recs if r["kind"] == "photo" and r.get("sharp") is not None and r["ext"] != ".png")
    return max(4.0, 0.25 * vals[len(vals) // 2]) if vals else 4.0


def resolve_dest(arg, src_info):
    """Where the copies go: what you asked for, else where they went last time, else next to the photos.
    Must be a new or empty folder, or one Snapsift made (it has sorted.csv), outside the photos folder."""
    src_dir = src_info.get("source", "")
    if src_dir and not os.path.isdir(src_dir):
        sys.exit(f"The photos folder isn't there ({src_dir}). Is the drive plugged in? Nothing was changed.")
    default = src_info.get("sorted") or (src_dir.rstrip("/") + " (sorted)" if src_dir else "")
    dest = os.path.abspath(os.path.expanduser(arg or default)) if (arg or default) else ""
    if not dest:
        sys.exit('Usage: python scripts/apply.py "/where/to/put/Sorted"')
    problem = dest_problem(dest, src_dir)
    if problem:
        sys.exit(problem)
    return dest


def dest_problem(dest, src_dir):
    if src_dir and inside(dest, src_dir):
        return "Put the sorted copies outside the photos folder, or the next scan would count them twice."
    if src_dir and inside(src_dir, dest):
        return "Put the sorted copies in their own folder, not in a folder that holds your photos folder."
    if os.path.realpath(dest) in ("/", os.path.realpath(os.path.expanduser("~"))):
        return "Pick a folder for the sorted copies, not your whole disk or home folder."
    if os.path.isdir(dest) and not os.path.exists(os.path.join(dest, "sorted.csv")) \
            and any(not f.startswith(".") for f in os.listdir(dest)):
        return "That folder already has other things in it. Pick a new or empty folder for the sorted copies."
    return None


def pick_labels(recs, cats):
    claude = read_labels()
    jev = load(JEV_OUT, {})
    if not claude and not jev:
        sys.exit("No labels yet. Label the files first (Claude: work/labels/*.json, or Jev: scripts/label_jev.py).")
    labels, flags, fixed, missing = {}, {}, 0, 0
    overrides = load(OVERRIDES, {})
    for r in recs:
        k = str(r["id"])
        j, c = jev.get(k, {}), claude.get(k, {})
        pick = j.get("key") if j.get("confidence", 0) >= 0.7 or k not in claude else c.get("k")
        pick = pick or c.get("k")
        if pick is None:
            missing += 1
        if pick not in cats or cats[pick]["kind"] != r["kind"]:  # photos only in photo folders, videos in video folders
            fixed += pick is not None
            pick = [x for x in cats.values() if x["kind"] == r["kind"]][-1]["key"]
        labels[k] = pick
        flags[k] = c.get("f", "")
    for k, v in overrides.items():  # moves made by hand in the dashboard win, and clear the review flags
        if k in labels and v in cats:
            labels[k], flags[k] = v, ""
    return labels, flags, claude, fixed, missing


def review_of(r, flag, dupe_of, overridden, blurry=4.0):
    if r["id"] in dupe_of:
        return "dupe"
    if overridden:
        return None
    if "s" in flag:
        return "private"
    if "j" in flag or (r["kind"] == "photo" and "error" not in r and r["ext"] != ".png"
                       and ((r.get("sharp") is not None and r["sharp"] < blurry) or (r.get("bright") is not None and r["bright"] < DARK))):
        return "junk"
    if "u" in flag:
        return "unsure"
    return None


def copy(src, dst):
    if sys.platform == "darwin" and subprocess.run(["cp", "-c", "-p", src, dst], capture_output=True).returncode == 0:
        return
    shutil.copy2(src, dst)


def fix_date(r, path):
    t = r.get("taken")
    if not t:
        return False
    os.utime(path, (t, t))
    if r["ext"] in (".jpg", ".jpeg") and not r.get("exif_date"):
        try:
            import piexif
            try:
                ex = piexif.load(path)
            except Exception:
                ex = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            stamp = time.strftime("%Y:%m:%d %H:%M:%S", time.localtime(t)).encode()
            ex.setdefault("Exif", {})[piexif.ExifIFD.DateTimeOriginal] = stamp
            ex["Exif"][piexif.ExifIFD.DateTimeDigitized] = stamp
            piexif.insert(piexif.dump(ex), path)  # lossless: the picture itself isn't re-encoded
            os.utime(path, (t, t))
        except Exception:
            pass  # the file date is still right
    return True


def old_copies(dest):
    """The copies this tool made last time, from sorted.csv: {absolute path: original path}.
    Rows pointing outside dest, at links or at missing files are ignored (sorted.csv is just a text file)."""
    out, csv_path = {}, os.path.join(dest, "sorted.csv")
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                p = os.path.join(dest, row.get("file") or "")
                if row.get("file") and inside(p, dest) and os.path.isfile(p) and not os.path.islink(p):
                    size = int(row["bytes"]) if (row.get("bytes") or "").isdigit() else None
                    out[os.path.normpath(p)] = (row.get("original_path") or "", row.get("folder") or "", size)
    return out


def untouched(path, size):
    """Still the copy we made: same size as when we wrote it (sorted.csv from older versions has no size)."""
    return size is None or os.path.getsize(path) == size


def prune_dirs(dirs, dest):
    """Remove folders that became empty because we removed our own copies from them. Nothing else."""
    for d in sorted(dirs, key=len, reverse=True):
        while d != dest and inside(d, dest) and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)


def main():
    src_info = load(os.path.join(DATA, "source.json"), {})
    dest = resolve_dest(sys.argv[1] if len(sys.argv) > 1 else "", src_info)
    opts = options()
    layout = opts.get("layout", "flat")
    do_dates = opts.get("fix_dates", True)
    do_albums = opts.get("albums", sys.platform == "darwin")

    recs = load(os.path.join(DATA, "inventory.json"))
    if not recs:
        sys.exit("Scan a folder first.")
    cats = {c["key"]: c for c in categories()}
    dupes = load(os.path.join(DATA, "dupes.json"), [])
    edits = {int(k): v for k, v in load(os.path.join(DATA, "edits.json"), {}).items()}
    events = load(os.path.join(DATA, "events.json"), [])
    overrides = load(OVERRIDES, {})
    labels, flags, claude, fixed, missing = pick_labels(recs, cats)

    dupe_of = {d: g for g in dupes for d in g["dupes"]}
    byid = {r["id"]: r for r in recs}
    review, blurry = {}, blur_limit(recs)
    for r in recs:
        k = str(r["id"])
        src_id = edits.get(r["id"])  # an edit follows its original
        if src_id is not None and str(src_id) in labels:
            labels[k] = labels[str(src_id)]
            rv = review_of(byid[src_id], flags.get(str(src_id), ""), dupe_of, str(src_id) in overrides, blurry)
            review[k] = None if rv == "dupe" else rv
        else:
            review[k] = review_of(r, flags.get(k, ""), dupe_of, k in overrides, blurry)

    save(os.path.join(DATA, "labels.json"), labels)
    save(os.path.join(DATA, "meta.json"), {k: {"c": claude.get(k, {}).get("c", ""), "f": flags.get(k, ""), "review": review[k]}
                                            for k in labels})
    src_info["sorted"] = dest
    save(os.path.join(DATA, "source.json"), src_info)
    shutil.copy(CATEGORIES, os.path.join(DATA, "categories.json"))

    os.makedirs(dest, exist_ok=True)
    old = old_copies(dest)  # nothing is removed until the new copies exist
    album_of = {}
    if do_albums:
        for e in events:
            name = safe_name(e["name"] if e.get("named") else e["auto_name"], limit=60)
            if e.get("named"):
                name += f" ({time.strftime('%b %Y', time.localtime(e['start']))})"
            for i in e["ids"]:
                album_of.setdefault(i, name)

    made, rows, gone, dated, blocked = set(), [], [], 0, []

    def place(r, folder):
        out_dir = os.path.join(dest, folder)
        os.makedirs(out_dir, exist_ok=True)
        b, e = os.path.splitext(r["name"])
        for cand in (r["name"], f"{b}__{r['id']}{e}", f"{b}__{r['id']}_2{e}"):
            t = os.path.normpath(os.path.join(out_dir, cand))
            if t in made:
                continue
            orig, _, size = old.get(t, ("", "", None))
            ours = orig == r["path"] and untouched(t, size)
            if os.path.lexists(t) and not ours:
                continue  # someone else's file, another photo's copy, or one you edited: never overwrite it
            if ours:
                return t, False  # last time's copy of the same photo, unchanged: keep it
            copy(r["path"], t)
            return t, True
        return None, False

    with open(os.path.join(dest, "duplicates.csv"), "w", newline="") as fd:
        wd = csv.writer(fd)
        wd.writerow(["duplicate", "kept_copy", "type", "kept_because", "duplicate_account", "kept_account", "duplicate_path", "kept_path"])
        for n, r in enumerate(recs, 1):
            k = str(r["id"])
            rv = review[k]
            if rv:
                folder = os.path.join(*REVIEW[rv])
            else:
                folder = folder_name(cats[labels[k]])
                if layout in ("year", "month"):
                    t = r.get("taken")
                    folder = os.path.join(folder, time.strftime("%Y" if layout == "year" else "%Y-%m", time.localtime(t)) if t else "Undated")
            if rv == "dupe":
                g = dupe_of[r["id"]]
                kp = byid[g["keep"]]
                wd.writerow([r["name"], kp["name"], g["type"], g.get("why", ""), r.get("account", ""), kp.get("account", ""), r["path"], kp["path"]])
            if not os.path.exists(r["path"]):
                gone.append(r["path"])
                continue
            targets = [folder] + ([os.path.join("Albums", album_of[r["id"]])] if r["id"] in album_of and not rv else [])
            for folder in targets:
                target, fresh = place(r, folder)
                if not target:
                    blocked.append(os.path.join(folder, r["name"]))
                    continue
                if fresh and do_dates and fix_date(r, target):
                    dated += 1
                made.add(target)
                rows.append([os.path.relpath(target, dest), folder, r["path"], os.path.getsize(target)])
            if n % 25 == 0 or n == len(recs):
                progress(n, len(recs))

    # last time's copies that aren't needed any more: remove them, unless their original is gone
    # (unplugged drive, deleted export): then that copy may be the only one left, so it stays
    kept_orphans, emptied = 0, set()
    for p, (orig, folder, size) in old.items():
        if p in made:
            continue
        if not orig or not os.path.exists(orig):
            rows.append([os.path.relpath(p, dest), folder, orig, size or ""])
            kept_orphans += 1
            continue
        if not untouched(p, size):
            continue  # you changed this copy: it's yours now, leave it (and stop tracking it)
        os.remove(p)
        emptied.add(os.path.dirname(p))
    prune_dirs(emptied, dest)
    tmp = os.path.join(dest, ".sorted.csv.tmp")
    with open(tmp, "w", newline="") as fc:
        wc = csv.writer(fc)
        wc.writerow(["file", "folder", "original_path", "bytes"])
        wc.writerows(rows)
    os.replace(tmp, os.path.join(dest, "sorted.csv"))

    counts = {}
    for k, rv in review.items():
        key = rv or labels[k]
        counts[key] = counts.get(key, 0) + 1
    print(f"Sorted into {dest}")
    for k, c in cats.items():
        print(f"  {c['label']:24} {counts.get(k, 0)}")
    for rv, parts in REVIEW.items():
        print(f"  {'/'.join(parts):24} {counts.get(rv, 0)}")
    if album_of:
        print(f"  {'Albums':24} {len(set(album_of.values()))} trips and events")
    if do_dates:
        print(f"  dates set on {dated} copies")
    if missing or fixed:
        print(f"  ({missing} files had no label and {fixed} had a wrong-type label; they went to the last folder of their kind)")
    if gone:
        print(f"  {len(gone)} originals were gone since the scan, e.g. {gone[0]}")
    if kept_orphans:
        print(f"  kept {kept_orphans} earlier copies whose originals are gone (they may be the only copies left)")
    if blocked:
        print(f"  {len(blocked)} copies skipped because a file Snapsift didn't make has that name, e.g. {blocked[0]}")


if __name__ == "__main__":
    main()
