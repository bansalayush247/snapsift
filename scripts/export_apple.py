"""Import the sorted library into Apple Photos (Mac), one album per folder, inside a "Snapsift" folder.

  python scripts/export_apple.py --dry-run          # what would be imported, nothing changes
  python scripts/export_apple.py [--include-albums]

Imports the sorted copies (with fixed dates), never the _Review folders. The first run asks for
permission to control Photos. Resumable: files already imported are skipped.
This ADDS photos to your Photos library (and iCloud Photos if it's on), so it asks before starting.
"""
import argparse, csv, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, WORK, load, progress, safe_name, save

STATE = os.path.join(WORK, "apple_import.json")
TOP = "Snapsift"
SCRIPT = """
on run argv
  set folderName to item 1 of argv
  set albumName to item 2 of argv
  set fileList to {}
  repeat with i from 3 to count of argv
    set end of fileList to (POSIX file (item i of argv)) as alias
  end repeat
  with timeout of 3600 seconds
    tell application "Photos"
      if not (exists folder folderName) then make new folder named folderName
      set f to folder folderName
      if not (exists album albumName of f) then make new album named albumName at f
      import fileList into (album albumName of f) skip check duplicates true
    end tell
  end timeout
end run
"""


def plan(include_albums):
    src = load(os.path.join(DATA, "source.json"), {})
    dest = src.get("sorted")
    if not dest or not os.path.exists(os.path.join(dest, "sorted.csv")):
        sys.exit("Sort first, then import the sorted folders.")
    by_path = {r["path"]: r["id"] for r in load(os.path.join(DATA, "inventory.json"), [])}
    albums = {}
    with open(os.path.join(dest, "sorted.csv"), newline="") as f:
        for row in csv.DictReader(f):
            parts = row["folder"].split(os.sep)
            if parts[0] == "_Review" or (parts[0] == "Albums" and not include_albums):
                continue
            title = safe_name(parts[1] if parts[0] == "Albums" and len(parts) > 1 else parts[0])
            i = by_path.get(row["original_path"])
            p = os.path.join(dest, row["file"])
            if i is not None and os.path.exists(p):
                albums.setdefault(title, []).append((i, p))
    return albums


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-albums", action="store_true")
    a = ap.parse_args(argv)
    if sys.platform != "darwin":
        sys.exit("Apple Photos import only works on a Mac.")
    albums = plan(a.include_albums)
    state = load(STATE, {})
    todo = {t: [(i, p) for i, p in items if t not in state.get(str(i), [])] for t, items in albums.items()}
    todo = {t: v for t, v in todo.items() if v}
    total = sum(len(v) for v in todo.values())
    if a.dry_run:
        for t, v in todo.items():
            print(f"  {TOP} / {t}: {len(v)} files")
        print(json.dumps({"files": total, "albums": len(todo)}), flush=True)
        return
    print(f"Importing {total} files into Apple Photos, {len(todo)} albums in the '{TOP}' folder...", flush=True)
    done = 0
    for title, items in todo.items():
        for s in range(0, len(items), 100):
            chunk = items[s:s + 100]
            r = subprocess.run(["osascript", "-e", SCRIPT, TOP, title] + [p for _, p in chunk],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if r.returncode:
                err = r.stderr.strip()
                if "-1743" in err or "not allowed" in err.lower():
                    sys.exit("macOS blocked access to Photos. Allow it in System Settings > Privacy & Security > Automation, then try again.")
                sys.exit(f"Photos couldn't import into '{title}': {err[:200]}")
            for i, _ in chunk:
                state.setdefault(str(i), []).append(title)
            save(STATE, state)
            done += len(chunk)
            progress(done, total)
    print(f"Done: {done} files imported into Apple Photos.", flush=True)


if __name__ == "__main__":
    main()
