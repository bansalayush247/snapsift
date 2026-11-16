"""Step 2: find duplicates.  python scripts/dupes.py

Exact = identical bytes (sha256). Near = looks the same (perceptual hash distance <= 4):
burst shots, re-saved screenshots, resized or "storage saver" copies.

Which copy is kept:
  1. a copy in your main account (when the folder holds several Google accounts)
  2. the highest resolution, then the sharpest (so a burst keeps its best shot), then the biggest file
The rest are listed in dashboard/data/dupes.json and later copied to _Review/Duplicates/.

Google Takeout also exports "-edited" versions next to the originals. Those are your edits, not
duplicates, so they are never put in a duplicate group: edits.json links each one to its original.
Also writes work/duplicates.jpg so you can eyeball the groups before trusting them.
"""
import os, re, sys

from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, THUMBS, WORK, load, progress, save
from scan import EDITED

NEAR = 4  # max differing bits out of 64


def pixels_differ(a, b):
    """Screenshots of the same app look identical to a perceptual hash (dark UI, same layout),
    so for PNGs also require almost no changed pixels: <0.4% of the preview."""
    with Image.open(os.path.join(THUMBS, f"{a}.jpg")) as A, Image.open(os.path.join(THUMBS, f"{b}.jpg")) as B:
        diff = ImageChops.difference(A.convert("L"), B.convert("L"))
        changed = sum(1 for p in diff.getdata() if p > 40)
        return changed / (A.width * A.height) > 0.004


def link_edits(recs):
    """'IMG_1-edited.jpg' -> the id of 'IMG_1.jpg' in the same folder."""
    by_place = {(os.path.dirname(r["path"]), r["name"].lower()): r["id"] for r in recs if not r.get("edited")}
    out = {}
    for r in recs:
        if r.get("edited"):
            orig = EDITED.sub(lambda m: os.path.splitext(m.group(0))[1], r["name"]).lower()
            hit = by_place.get((os.path.dirname(r["path"]), orig))
            if hit is None:  # Takeout sometimes changes the extension case or format
                stem = os.path.splitext(orig)[0]
                hit = next((i for (d, n), i in by_place.items() if d == os.path.dirname(r["path"]) and os.path.splitext(n)[0] == stem), None)
            if hit is not None:
                out[str(r["id"])] = hit
    return out


def candidate_pairs(hashed):
    """Pairs that could be within NEAR bits. Split the 64-bit hash into NEAR+1 pieces: two hashes
    that differ in <= NEAR bits must match exactly on at least one piece (pigeonhole), so we only
    compare within buckets instead of every file against every other."""
    widths = [64 // (NEAR + 1)] * (NEAR + 1)
    widths[-1] += 64 - sum(widths)
    seen = set()
    for n, w in enumerate(widths):
        shift = sum(widths[n + 1:])
        buckets = {}
        for rid, kind, h in hashed:
            buckets.setdefault((kind, (h >> shift) & ((1 << w) - 1)), []).append((rid, h))
        for b in buckets.values():
            for i in range(len(b)):
                for j in range(i + 1, len(b)):
                    pair = (b[i][0], b[j][0])
                    if pair not in seen and bin(b[i][1] ^ b[j][1]).count("1") <= NEAR:
                        seen.add(pair)
                        yield pair


def keeper_order(g, main, exact):
    def key(r):
        in_main = 0 if main and r.get("account") == main else 1
        copy_name = 1 if re.search(r"\(\d+\)\.\w+$", r["name"]) else 0
        if exact:
            return (in_main, copy_name, len(r["path"]))
        return (in_main, -(r.get("w") or 0) * (r.get("h") or 0), -(r.get("sharp") or 0), -r["bytes"], copy_name, len(r["name"]))
    return sorted(g, key=key)


def main():
    recs = load(os.path.join(DATA, "inventory.json"))
    if not recs:
        sys.exit("Scan a folder first.")
    src = load(os.path.join(DATA, "source.json"), {})
    main_acct = src.get("main_account")
    edits = link_edits(recs)
    byid = {r["id"]: r for r in recs}
    pool = [r for r in recs if not r.get("edited")]
    parent = {r["id"]: r["id"] for r in pool}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(b)] = find(a)

    by_sha = {}
    for r in pool:
        by_sha.setdefault(r["sha256"], []).append(r["id"])
    for ids in by_sha.values():
        for x in ids[1:]:
            union(ids[0], x)

    hashed = [(r["id"], r["kind"], int(r["phash"], 16)) for r in pool if r.get("phash") and "error" not in r]
    checked = 0
    for a, b in candidate_pairs(hashed):
        checked += 1
        if checked % 500 == 0:
            progress(min(checked, len(hashed)), len(hashed))
        ra, rb = byid[a], byid[b]
        if ra["ext"] == ".png" and rb["ext"] == ".png" and ra["sha256"] != rb["sha256"] and pixels_differ(a, b):
            continue
        union(a, b)
    progress(len(hashed), len(hashed))

    groups = {}
    for r in pool:
        groups.setdefault(find(r["id"]), []).append(r)
    out = []
    for g in groups.values():
        if len(g) < 2:
            continue
        exact = len({r["sha256"] for r in g}) == 1
        g = keeper_order(g, main_acct, exact)
        k = g[0]
        why = "in your main account" if main_acct and k.get("account") == main_acct and any(r.get("account") != main_acct for r in g) \
            else "identical copy" if exact else "highest resolution" if (k.get("w") or 0) * (k.get("h") or 0) > (g[1].get("w") or 0) * (g[1].get("h") or 0) \
            else "sharpest" if (k.get("sharp") or 0) > (g[1].get("sharp") or 0) else "biggest file"
        out.append({"keep": k["id"], "dupes": [r["id"] for r in g[1:]], "type": "exact" if exact else "near",
                    "why": why, "freed": sum(r["bytes"] for r in g[1:]),
                    "accounts": sorted({r.get("account") for r in g if r.get("account")})})
    out.sort(key=lambda g: -g["freed"])
    save(os.path.join(DATA, "dupes.json"), out)
    save(os.path.join(DATA, "edits.json"), edits)

    # contact sheet: one row per group, keeper first
    if out:
        rows = [[g["keep"]] + g["dupes"] for g in out][:60]
        W = min(max(map(len, rows)), 8)
        sheet = Image.new("RGB", (W * 170, len(rows) * 170), "white")
        d = ImageDraw.Draw(sheet)
        for y, row in enumerate(rows):
            for x, i in enumerate(row[:W]):
                with Image.open(os.path.join(THUMBS, f"{i}.jpg")) as t:
                    sheet.paste(t.resize((160, 160)), (x * 170, y * 170))
                d.rectangle((x * 170, y * 170, x * 170 + 60, y * 170 + 14), fill="black")
                d.text((x * 170 + 3, y * 170 + 2), ("KEEP " if x == 0 else "") + str(i), fill="yellow")
        os.makedirs(WORK, exist_ok=True)
        sheet.save(os.path.join(WORK, "duplicates.jpg"), quality=80)

    n = sum(len(g["dupes"]) for g in out)
    print(f"{len(out)} duplicate groups, {n} extra copies, {sum(g['freed'] for g in out) / 1e9:.2f} GB could be freed"
          + (f", {len(edits)} edited versions linked to their originals" if edits else "")
          + ("  (preview: work/duplicates.jpg)" if out else ""), flush=True)


if __name__ == "__main__":
    main()
