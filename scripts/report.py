"""Step 5: the clean-up report.  python scripts/report.py

  dashboard/data/report.json          what the dashboard shows under Accounts and Clean up
  <sorted>/_Review/Delete lists/      one CSV per account: copies you can delete there, because the
                                      same photo is kept elsewhere (Google has no way for apps to delete
                                      photos, so you delete them yourself in photos.google.com)

Per account: files, size, and how much space deleting its duplicates would free. Also the biggest
videos, and the files flagged junk, private or not sure. Nothing here deletes anything.
"""
import csv, os, sys, time

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, load, safe_name, save


def main():
    recs = load(os.path.join(DATA, "inventory.json"), [])
    src = load(os.path.join(DATA, "source.json"), {})
    dupes = load(os.path.join(DATA, "dupes.json"), [])
    meta = load(os.path.join(DATA, "meta.json"), {})
    byid = {r["id"]: r for r in recs}
    kept_by = {d: g for g in dupes for d in g["dupes"]}

    accounts = {}
    for r in recs:
        a = accounts.setdefault(r.get("account") or "", {"name": r.get("account") or "", "files": 0, "bytes": 0, "photos": 0,
                                                          "videos": 0, "dupes": 0, "dupe_bytes": 0, "elsewhere": 0, "elsewhere_bytes": 0})
        a["files"] += 1
        a["bytes"] += r["bytes"]
        a["photos" if r["kind"] == "photo" else "videos"] += 1
        g = kept_by.get(r["id"])
        if g:
            a["dupes"] += 1
            a["dupe_bytes"] += r["bytes"]
            if byid[g["keep"]].get("account") != r.get("account"):
                a["elsewhere"] += 1
                a["elsewhere_bytes"] += r["bytes"]

    lists = {}
    sorted_dir = src.get("sorted")
    if sorted_dir and os.path.isdir(sorted_dir):
        out_dir = os.path.join(sorted_dir, "_Review", "Delete lists")
        os.makedirs(out_dir, exist_ok=True)
        for f in os.listdir(out_dir):  # this tool's own lists from last time
            if f.startswith("delete-from-") and f.endswith(".csv"):
                os.remove(os.path.join(out_dir, f))
        rows = {}
        for d, g in kept_by.items():
            r, k = byid[d], byid[g["keep"]]
            rows.setdefault(r.get("account") or "all", []).append([
                r["name"], time.strftime("%Y-%m-%d %H:%M", time.localtime(r["taken"])) if r.get("taken") else "",
                r.get("album", ""), f"{r['bytes'] / 1e6:.1f} MB", "identical" if g["type"] == "exact" else "looks the same",
                k.get("account", ""), k["name"], g.get("why", ""), r["path"]])
        for acct, rs in rows.items():
            rs.sort(key=lambda x: (x[1], x[0]))
            name = f"delete-from-{safe_name(acct, 'all', 60)}.csv"
            with open(os.path.join(out_dir, name), "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["file", "taken", "album_folder", "size", "match", "kept_in_account", "kept_file", "kept_because", "path_in_export"])
                w.writerows(rs)
            lists[acct] = os.path.join(out_dir, name)

    flagged = {f: [int(k) for k, v in meta.items() if v.get("review") == f] for f in ("private", "junk", "unsure")}
    videos = sorted((r for r in recs if r["kind"] == "video"), key=lambda r: -r["bytes"])[:40]
    report = {
        "accounts": sorted(accounts.values(), key=lambda a: -a["bytes"]) if any(r.get("account") for r in recs) else [],
        "main_account": src.get("main_account"),
        "delete_lists": lists,
        "dupe_bytes": sum(g["freed"] for g in dupes),
        "dupe_files": len(kept_by),
        "big_videos": [r["id"] for r in videos],
        "big_videos_bytes": sum(r["bytes"] for r in videos),
        **flagged,
        "when": int(time.time()),
    }
    save(os.path.join(DATA, "report.json"), report)
    print(f"Report: {len(report['accounts'])} accounts, {report['dupe_files']} duplicate copies "
          f"({report['dupe_bytes'] / 1e9:.2f} GB), {len(flagged['junk'])} junk, {len(flagged['private'])} private, "
          f"{len(flagged['unsure'])} not sure" + (f"; delete lists in {os.path.dirname(next(iter(lists.values())))}" if lists else ""), flush=True)


if __name__ == "__main__":
    main()
