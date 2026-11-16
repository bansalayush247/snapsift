"""Step 1: inventory a photo folder (any folder, Google Takeout, Apple Photos export...).

  python scripts/scan.py "/path/to/photos"              # everything
  python scripts/scan.py "/path/to/photos" --limit 200  # try a sample first
  python scripts/scan.py "/path/to/photos" --accounts   # each subfolder is a different account
  python scripts/scan.py "/path/to/photos" --fresh      # forget the last scan and start over

Records size, sha256, dimensions, video length, the date taken, place and camera (from the photo
itself or Google Takeout's .json sidecar), how sharp and how bright it is, and makes a 256px square
preview in dashboard/data/thumbs/. Read-only on your photos.

Scanning the same folder again only looks at new or changed files, and keeps every earlier label.
"""
import argparse, calendar, hashlib, json, os, random, re, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageFilter, ImageOps, ImageStat
import imagehash

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, IMG, MINI, THUMBS, VID, load, progress, save

# Only real video containers: a ".mp4" that is really a playlist (HLS, concat) could make ffmpeg read
# other files on this computer into the preview, which is then shown to Claude.
VIDEO_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi"
EDITED = re.compile(r"-(edited|bearbeitet|modifi[ée]|editado|modificato|bewerkt|redigerad|muokattu)(\(\d+\))?\.\w+$", re.I)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--limit", type=int, default=0, help="only scan a random sample of N files")
    ap.add_argument("--accounts", action="store_true", help="each top-level subfolder is a different account")
    ap.add_argument("--fresh", action="store_true", help="ignore the previous scan")
    return ap.parse_args(argv)


_listing = {}


def sidecar(path):
    """Google Takeout writes '<file>.json' or '<file>.supplemental-metadata.json' (often truncated)."""
    d, name = os.path.split(path)
    if d not in _listing:
        _listing[d] = [f for f in os.listdir(d) if f.endswith(".json")]
    m = re.match(r"(.*?)(\(\d+\))(\.\w+)$", name)  # IMG_1(1).JPG -> IMG_1.JPG...(1).json
    for f in _listing[d]:
        if m and f.startswith(m.group(1) + m.group(3)) and f.endswith(m.group(2) + ".json"):
            return os.path.join(d, f)
        if not m and f.startswith(name + ".") and not re.search(r"\(\d+\)\.json$", f):
            return os.path.join(d, f)
    # Takeout cuts long names to 46 characters before adding .json
    base = name[:46]
    for f in _listing[d]:
        if len(name) > 46 and f.startswith(base) and not re.search(r"\(\d+\)\.json$", f):
            return os.path.join(d, f)
    return None


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def square(im, size=256):
    im = im.convert("RGB")
    s = min(im.size)
    left, top = (im.width - s) // 2, (im.height - s) // 2
    return im.crop((left, top, left + s, top + s)).resize((size, size))


LAPLACE = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


def quality(thumb):
    """Sharpness (spread of edges; below ~6 is very blurry) and brightness (0 black .. 255 white)."""
    g = thumb.convert("L")
    return round(ImageStat.Stat(g.filter(LAPLACE)).stddev[0], 2), round(ImageStat.Stat(g).mean[0], 1)


def _ratio(v):
    try:
        return float(v[0]) / float(v[1]) if isinstance(v, tuple) else float(v)
    except (TypeError, ZeroDivisionError, ValueError):
        return 0.0


def exif_info(im):
    """Date taken (unix time, read as local time), GPS and camera from the photo's EXIF."""
    out = {}
    try:
        ex = im.getexif()
    except Exception:
        return out
    if not ex:
        return out
    sub = ex.get_ifd(0x8769) if hasattr(ex, "get_ifd") else {}
    when = sub.get(36867) or sub.get(36868) or ex.get(306)
    if when:
        try:
            out["taken"] = int(time.mktime(time.strptime(str(when).strip("\x00")[:19], "%Y:%m:%d %H:%M:%S")))
            out["exif_date"] = True
        except (ValueError, OverflowError):
            pass
    make, model = str(ex.get(271, "")).strip("\x00 "), str(ex.get(272, "")).strip("\x00 ")
    if model:
        out["camera"] = model if make.split(" ")[0].lower() in model.lower() else f"{make} {model}".strip()
    lens = str(sub.get(42036, "")).strip("\x00 ")
    if lens:
        out["lens"] = lens[:60]
    try:
        gps = ex.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            lat = sum(_ratio(x) / 60 ** i for i, x in enumerate(gps[2]))
            lon = sum(_ratio(x) / 60 ** i for i, x in enumerate(gps[4]))
            if str(gps.get(1, "N")).upper().startswith("S"):
                lat = -lat
            if str(gps.get(3, "E")).upper().startswith("W"):
                lon = -lon
            if (lat or lon) and abs(lat) <= 90 and abs(lon) <= 180:
                out["geo"] = [round(lat, 6), round(lon, 6)]
    except Exception:
        pass
    return out


def video_info(path, thumb, has_ffmpeg):
    if not has_ffmpeg:
        return {}
    r = subprocess.run(["ffprobe", "-v", "error", "-format_whitelist", VIDEO_FORMATS, "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_tags=rotate:format=duration:format_tags=creation_time,location",
                        "-of", "json", path], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout or "{}")
    except ValueError:
        j = {}
    s = (j.get("streams") or [{}])[0]
    w, h = s.get("width", 0), s.get("height", 0)
    if str(s.get("tags", {}).get("rotate", "0")) in ("90", "-90", "270"):
        w, h = h, w
    fmt = j.get("format", {})
    dur = float(fmt.get("duration", 0) or 0)
    out = {"w": w, "h": h, "duration": dur}
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    if tags.get("creation_time"):
        try:
            out["taken"] = calendar.timegm(time.strptime(tags["creation_time"][:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            pass
    m = re.match(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", tags.get("location", ""))  # ISO 6709, iPhone videos
    if m:
        out["geo"] = [float(m.group(1)), float(m.group(2))]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-format_whitelist", VIDEO_FORMATS, "-ss", "1" if dur > 2 else "0", "-i", path, "-frames:v", "1",
                    "-vf", "scale=256:256:force_original_aspect_ratio=increase,crop=256:256", thumb],
                   capture_output=True, stdin=subprocess.DEVNULL)
    return out


def make_process(src, accounts, has_ffmpeg):
    def process(job):
        i, path = job
        st = os.stat(path)
        ext = os.path.splitext(path)[1].lower()
        kind = "video" if ext in VID else "photo"
        rel = os.path.relpath(path, src)
        rec = {"id": i, "path": path, "name": os.path.basename(path), "ext": ext, "kind": kind,
               "bytes": st.st_size, "mtime": int(st.st_mtime), "sha256": sha(path)}
        if accounts:
            rec["account"] = rel.split(os.sep)[0] if os.sep in rel else "(top folder)"
        parts = rel.split(os.sep)
        if len(parts) > 1:
            rec["album"] = parts[-2]  # Takeout puts photos in album / year folders
        if EDITED.search(rec["name"]):
            rec["edited"] = True
        thumb = os.path.join(THUMBS, f"{i}.jpg")
        try:
            if kind == "video":
                rec.update(video_info(path, thumb, has_ffmpeg))
                if not os.path.exists(thumb):  # no ffmpeg: grey placeholder so the dashboard still works
                    Image.new("RGB", (256, 256), (60, 60, 66)).save(thumb)
            else:
                with Image.open(path) as im:
                    rec["w"], rec["h"] = im.size
                    rec.update(exif_info(im))
                    im.draft("RGB", (512, 512))
                    square(ImageOps.exif_transpose(im)).save(thumb, quality=80)
            with Image.open(thumb) as t:
                rec["phash"] = str(imagehash.phash(t))
                rec["sharp"], rec["bright"] = quality(t)
                t.convert("RGB").resize((72, 72)).save(os.path.join(MINI, f"{i}.jpg"), quality=72)
        except Exception as e:  # unreadable file: keep it in the inventory, flag it
            rec["error"] = str(e)[:200]
            Image.new("RGB", (256, 256), (230, 228, 222)).save(thumb)
            Image.new("RGB", (72, 72), (230, 228, 222)).save(os.path.join(MINI, f"{i}.jpg"))
        sc = sidecar(path)
        if sc:
            try:
                with open(sc) as f:
                    j = json.load(f)
                t = int((j.get("photoTakenTime") or {}).get("timestamp", 0) or 0)
                if t:
                    rec["taken"], rec["taken_src"] = t, "takeout"
                g = j.get("geoData") or {}
                if g.get("latitude") or g.get("longitude"):
                    rec["geo"] = [g["latitude"], g["longitude"]]
            except Exception:
                pass
        if rec.get("taken") and "taken_src" not in rec:
            rec["taken_src"] = "exif" if rec.get("exif_date") else "video"
        return rec
    return process


def main(argv=None):
    args = parse_args(argv)
    src = os.path.abspath(os.path.expanduser(args.source))
    if not os.path.isdir(src):
        sys.exit(f"Folder not found: {src}")
    has_ffmpeg = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    prev_src = load(os.path.join(DATA, "source.json"), {})
    old = [] if args.fresh or prev_src.get("source") != src or bool(prev_src.get("accounts")) != args.accounts \
        else load(os.path.join(DATA, "inventory.json"), [])
    if not old:
        for d in (THUMBS, MINI):
            shutil.rmtree(d, ignore_errors=True)
    for d in (THUMBS, MINI):
        os.makedirs(d, exist_ok=True)

    files = []
    for dp, dirs, fs in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not d.endswith(" (sorted)") and not d.endswith(".photoslibrary"))
        files += [os.path.join(dp, f) for f in sorted(fs) if os.path.splitext(f)[1].lower() in IMG | VID and not f.startswith(".")]
    if not files:
        sys.exit("No photos or videos found in that folder.")
    if args.limit and args.limit < len(files):
        files = sorted(random.Random(0).sample(files, args.limit))

    # keep what we already know about unchanged files (same path, size and time), so ids and labels survive
    by_path = {r["path"]: r for r in old}
    keep, todo = [], []
    for p in files:
        r = by_path.get(p)
        try:
            st = os.stat(p)
        except OSError:
            continue
        if r and r["bytes"] == st.st_size and r.get("mtime") == int(st.st_mtime) \
                and os.path.exists(os.path.join(THUMBS, f"{r['id']}.jpg")):
            keep.append(r)
        else:
            todo.append(p)
    kept_ids = {r["id"] for r in keep}
    for r in old:  # files that disappeared or changed: drop their previews
        if r["id"] not in kept_ids:
            for d in (THUMBS, MINI):
                try:
                    os.remove(os.path.join(d, f"{r['id']}.jpg"))
                except OSError:
                    pass
    next_id = max([r["id"] for r in old] + [-1]) + 1
    jobs = [(next_id + n, p) for n, p in enumerate(todo)]

    print(f"Scanning {len(files)} files" + (f" ({len(keep)} already known, {len(todo)} new or changed)" if old else "") + "...", flush=True)
    if not has_ffmpeg and any(os.path.splitext(f)[1].lower() in VID for f in todo):
        print("  note: ffmpeg not installed, videos will get grey previews (Mac: brew install ffmpeg)")

    process = make_process(src, args.accounts, has_ffmpeg)
    recs = list(keep)
    with ThreadPoolExecutor(8) as ex:
        for n, r in enumerate(ex.map(process, jobs), 1):
            recs.append(r)
            if n % 20 == 0 or n == len(jobs):
                progress(n, len(jobs))
            if n % 200 == 0:
                print(f"  {n}/{len(jobs)}", flush=True)
    if not jobs:
        progress(1, 1)
    recs.sort(key=lambda r: r["id"])

    save(os.path.join(DATA, "inventory.json"), recs)
    info = dict(prev_src) if old else {k: prev_src[k] for k in ("options",) if k in prev_src}
    info.update(source=src, limit=args.limit, accounts=args.accounts, new_ids=[r["id"] for r in recs if r["id"] >= next_id])
    save(os.path.join(DATA, "source.json"), info)
    bad = [r["name"] for r in recs if "error" in r]
    print(f"Done: {len(recs)} files ({sum(r['kind'] == 'video' for r in recs)} videos), "
          f"{sum(r['bytes'] for r in recs) / 1e9:.1f} GB" + (f", {len(todo)} new" if old else "")
          + (f", {len(bad)} unreadable: {bad[:5]}" if bad else ""), flush=True)


if __name__ == "__main__":
    main()
