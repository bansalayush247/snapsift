"""The dashboard app.  python scripts/server.py   ->  http://127.0.0.1:8765

Serves dashboard/ plus a small local API so the page can do everything itself: pick folders, peek at
a folder, run the whole sort (scan, duplicates, Claude labels, trips & events, build folders, report)
with live progress, edit folders, browse photos at full size, move a photo to another folder, open
folders in Finder, and the extras (highlights, Google Photos upload, Apple Photos import, Trash).

Security: listens on 127.0.0.1 only; answers only requests addressed to 127.0.0.1/localhost on this
port (stops DNS-rebinding sites from reading your photos); state-changing calls must come from this
page (Origin + JSON content type); strict Content-Security-Policy; no directory listings.
"""
import glob, hashlib, io, json, mimetypes, os, random, re, shutil, signal, subprocess, sys, threading, time, urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(__file__))
from common import (CATEGORIES, DATA, HOME, IMG, JEV_OUT, LABELS, MODELS, OVERRIDES, ROOT, SECRETS, VID, WORK, find_claude,
                    folder_name, inside, load, read_labels, save)

PORT = int(os.environ.get("PORT", 8765))
DASH = os.path.join(ROOT, "dashboard")
PEEK = os.path.join(HOME, "dashboard", "peek")
SCRIPTS = os.path.join(ROOT, "scripts")
PY = sys.executable
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ORIGINS = {f"http://{h}" for h in HOSTS}
MAX_BODY = 1 << 20
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob: https://tile.openstreetmap.org; media-src 'self' blob:; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
LAYOUTS = ("flat", "year", "month")
NAMES = {"scan": "Scan", "dupes": "Duplicates", "label": "Label", "events": "Trips", "apply": "Folders", "report": "Report",
         "highlights": "Highlights", "google_login": "Google sign-in", "google_upload": "Upload", "apple_import": "Import",
         "trash": "Trash", "events_name": "Names"}
job = {"step": None, "running": False, "log": [], "code": None, "phase": None, "phases": [], "done": 0, "total": 0,
       "started": None, "phase_started": None, "timings": {}, "proc": None, "stop": False}
lock = threading.Lock()


def has_jev_key():
    if os.environ.get("JEV_KEY") or os.environ.get("TYPESAFE_API_KEY"):
        return True
    env = os.path.join(ROOT, ".env")
    return os.path.exists(env) and bool(re.search(r"^(JEV_KEY|TYPESAFE_API_KEY)=\S", open(env).read(), re.M))


def google_light():
    tok = load(os.path.join(SECRETS, "google_token.json"), {}) or {}
    return {"configured": os.path.exists(os.path.join(SECRETS, "google_client.json")),
            "signed_in": bool(tok.get("refresh_token")), "email": tok.get("email", ""),
            "uploaded": len((load(os.path.join(WORK, "google_upload.json"), {}) or {}).get("items", {}))}


def state():
    inv = load(os.path.join(DATA, "inventory.json"), [])
    src = load(os.path.join(DATA, "source.json"), {})
    accounts = sorted({r.get("account") for r in inv if r.get("account")})
    return {
        "categories": load(CATEGORIES, []),
        "source": src.get("source"), "limit": src.get("limit"), "sorted": src.get("sorted"),
        "options": src.get("options", {}), "accounts": accounts, "main_account": src.get("main_account"),
        "files": len(inv), "bytes": sum(r["bytes"] for r in inv),
        "steps": {
            "scan": bool(inv),
            "dupes": os.path.exists(os.path.join(DATA, "dupes.json")),
            "label": bool(glob.glob(os.path.join(LABELS, "*.json"))) or os.path.exists(JEV_OUT),
            "jev_labels": os.path.exists(JEV_OUT),
            "apply": bool(src.get("sorted")) and os.path.exists(os.path.join(DATA, "labels.json")),
            "report": os.path.exists(os.path.join(DATA, "report.json")),
            "events": os.path.exists(os.path.join(DATA, "events.json")),
            "highlights": os.path.exists(os.path.join(DATA, "highlights.json")),
        },
        "jev_key": has_jev_key(),
        "claude_cli": bool(find_claude()),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "google": google_light(),
        "trashed": len(load(os.path.join(DATA, "trashed.json"), [])),
        "overrides": len(load(OVERRIDES, {})),
        "job": {k: job[k] for k in ("step", "running", "code", "phase", "phases", "done", "total", "started", "phase_started", "timings")}
               | {"log": job["log"][-40:], "now": time.time()},
        "platform": sys.platform,
    }


def live_labels():
    """Labels written so far (Claude batches + confident Jev answers), for the live animation."""
    out = {k: v["k"] for k, v in read_labels().items()}
    for k, v in load(JEV_OUT, {}).items():
        if "key" in v and (v.get("confidence", 0) >= 0.7 or k not in out):
            out[k] = v["key"]
    return out


def clear_library():
    """A new folder (or sample size) means the old labels no longer match."""
    for f in ("labels.json", "dupes.json", "meta.json", "edits.json", "events.json", "report.json", "highlights.json", "trashed.json"):
        p = os.path.join(DATA, f)
        if os.path.exists(p):
            os.remove(p)
    for f in (JEV_OUT, OVERRIDES):
        if os.path.exists(f):
            os.remove(f)
    for d in (LABELS, os.path.join(WORK, "sheets")):
        shutil.rmtree(d, ignore_errors=True)


def categories_fingerprint():
    return hashlib.sha1(open(CATEGORIES, "rb").read()).hexdigest()[:12]


def stream(cmd, env=None):
    """Run one script, keep its output for the log, and read PROGRESS lines."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT, env=env,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    job["proc"] = p
    for line in p.stdout:
        line = line.rstrip()
        m = re.match(r"PROGRESS (\d+) (\d+)", line)
        if m:
            job["done"], job["total"] = int(m.group(1)), int(m.group(2))
        else:
            job["log"].append(line)
            del job["log"][:-400]
    code = p.wait()
    job["proc"] = None
    return code


def start_job(step, phases, body):
    with lock:
        if job["running"]:
            raise RuntimeError("Something is already running. Wait for it to finish.")
        now = time.time()
        job.update(step=step, running=True, log=[f"$ {step}"], code=None, phase=None, phases=phases, done=0, total=0,
                   started=now, phase_started=now, timings={}, stop=False)

    def wrapped():
        try:
            body()
        except Exception as e:  # never leave the dashboard thinking something is still running
            job["log"].append(f"Error: {e}")
            job.update(running=False, code=1)
    threading.Thread(target=wrapped, daemon=True).start()


def run_phase(name, cmd, env=None):
    if job["stop"]:
        job["log"].append("Stopped.")
        return 1
    job.update(phase=name, done=0, total=0, phase_started=time.time())
    code = stream([PY, "-u"] + cmd, env)
    job["timings"][name] = round(time.time() - job["phase_started"], 1)
    return 1 if job["stop"] else code


def script(name, *args):
    return [os.path.join(SCRIPTS, name)] + [str(a) for a in args]


def child_env():
    env = dict(os.environ)
    m = load(os.path.join(DATA, "source.json"), {}).get("options", {}).get("model")
    if m in MODELS:
        env["CLAUDE_MODEL"] = m
    return env


def clean_options(args):
    return {"model": args.get("model") if args.get("model") in MODELS else "sonnet",
            "layout": args.get("layout") if args.get("layout") in LAYOUTS else "flat",
            "fix_dates": bool(args.get("fix_dates", True)), "albums": bool(args.get("albums", sys.platform == "darwin")),
            "second_look": bool(args.get("second_look", True))}


def check_dest(source, dest):
    from apply import dest_problem
    dest = os.path.abspath(os.path.expanduser(dest or source.rstrip("/") + " (sorted)"))
    problem = dest_problem(dest, source)
    if problem:
        raise ValueError(problem)
    return dest


def sort_all(args):
    source = os.path.abspath(os.path.expanduser((args.get("source") or "").strip())) if (args.get("source") or "").strip() else ""
    if not source or not os.path.isdir(source):
        raise ValueError("Choose the folder with your photos first.")
    dest = check_dest(source, (args.get("dest") or "").strip())
    limit = max(0, min(int(args.get("limit") or 0), 1_000_000))
    labeler = "jev" if args.get("labeler") == "jev" else "claude"
    accounts = bool(args.get("accounts"))
    if labeler == "claude" and not find_claude():
        raise ValueError("Claude Code is not installed, so it can't label the photos. Install it, or use Jev under Advanced.")
    if labeler == "jev" and not has_jev_key():
        raise ValueError("Add JEV_KEY=your-key to a .env file in this folder to use Jev.")
    src = load(os.path.join(DATA, "source.json"), {})
    fresh = src.get("source") != source or int(src.get("limit") or 0) != limit or bool(src.get("accounts")) != accounts
    opts = clean_options(args)
    phases = ["scan", "dupes", "label", "events", "apply", "report"]

    def body():
        def fail():
            job.update(running=False, code=1)
        if fresh:
            clear_library()
        info = load(os.path.join(DATA, "source.json"), {})
        info["options"] = opts
        if fresh:
            info.pop("main_account", None)
        save(os.path.join(DATA, "source.json"), info)
        env = child_env()
        if run_phase("scan", script("scan.py", source, "--limit", limit, *(["--accounts"] if accounts else []), *(["--fresh"] if fresh else []))):
            return fail()
        if run_phase("dupes", script("dupes.py")):
            return fail()
        marker = os.path.join(LABELS, ".categories")
        if load(marker) != categories_fingerprint():  # folders changed since the last labels
            shutil.rmtree(LABELS, ignore_errors=True)
            if os.path.exists(JEV_OUT):
                os.remove(JEV_OUT)
        os.makedirs(LABELS, exist_ok=True)
        save(marker, categories_fingerprint())
        if run_phase("label", script("label_jev.py" if labeler == "jev" else "label_claude.py"), env):
            total = len(load(os.path.join(DATA, "inventory.json"), []))
            if job["stop"] or not total or len(live_labels()) < 0.95 * total:
                return fail()
            job["log"].append("A few files could not be labelled; they go to the catch-all folders.")
        if run_phase("events", script("events.py")):
            return fail()
        if run_phase("apply", script("apply.py", dest)):
            return fail()
        run_phase("report", script("report.py"))
        job.update(running=False, code=0, phase="done")
    start_job("sort", phases, body)


def run_steps(step, steps):
    """steps: [(phase name, script args)] run one after another."""
    def body():
        env = child_env()
        for name, cmd in steps:
            if run_phase(name, cmd, env):
                return job.update(running=False, code=1)
        job.update(running=False, code=0, phase="done")
    start_job(step, [s[0] for s in steps], body)


def run_single(step, args):
    if not load(os.path.join(DATA, "source.json"), {}).get("sorted") and step not in ("google_login",):
        raise ValueError("Sort first.")
    if step == "highlights":
        year = int(args["year"]) if str(args.get("year") or "").isdigit() else None
        run_steps(step, [("highlights", script("highlights.py", *(["--year", year] if year else []), *(["--local"] if args.get("local") else [])))])
    elif step == "events_name":
        run_steps(step, [("events_name", script("events.py", "--name")), ("apply", script("apply.py")), ("report", script("report.py"))])
    elif step == "google_login":
        run_steps(step, [("google_login", script("upload_google.py", "--login"))])
    elif step == "google_upload":
        run_steps(step, [("google_upload", script("upload_google.py", *(["--strip-location"] if args.get("strip") else []),
                                                  *(["--include-albums"] if args.get("albums") else [])))])
    elif step == "apple_import":
        run_steps(step, [("apple_import", script("export_apple.py", *(["--include-albums"] if args.get("albums") else [])))])
    elif step == "trash":
        n = args.get("confirm")
        if not isinstance(n, int) or n <= 0:
            raise ValueError("Confirm how many files to move to the Trash.")
        run_steps(step, [("trash", script("trash_dupes.py", "--confirm", n, *(["--near"] if args.get("near") else []))),
                         ("report", script("report.py"))])
    elif step == "rebuild":
        run_steps(step, [("dupes", script("dupes.py")), ("events", script("events.py")), ("apply", script("apply.py")), ("report", script("report.py"))])
    else:
        raise ValueError("unknown step")


def quick(cmd):
    r = subprocess.run([PY] + cmd, capture_output=True, text=True, cwd=ROOT, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise ValueError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else "failed")
    return json.loads(r.stdout.strip().splitlines()[-1])


def looks_takeout(d, depth=3):
    """A Google Takeout export has a 'Takeout' or 'Google Photos' folder near the top."""
    base = d.rstrip(os.sep).count(os.sep)
    for dp, dirs, _ in os.walk(d):
        if any(x in ("Takeout", "Google Photos", "Google Fotos") for x in dirs):
            return True
        if dp.count(os.sep) - base >= depth - 1:
            dirs[:] = []
    return False


def media_count(d, cap=400000):
    n = 0
    for dp, dirs, fs in os.walk(d):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        n += sum(1 for f in fs if os.path.splitext(f)[1].lower() in IMG | VID)
        if n > cap:
            break
    return n


def peek(source):
    """Count what is in a folder and make a few tiny previews, right after it is picked."""
    source = os.path.abspath(os.path.expanduser(source.strip()))
    if not os.path.isdir(source):
        raise ValueError("That folder does not exist.")
    photos, videos, size, pics = 0, 0, 0, []
    for dp, dirs, fs in os.walk(source):
        dirs[:] = [d for d in dirs if not d.startswith(".") and not d.endswith(" (sorted)") and not d.endswith(".photoslibrary")]
        for f in fs:
            ext = os.path.splitext(f)[1].lower()
            if f.startswith("."):
                continue
            if ext in IMG:
                photos += 1
                if ext in (".jpg", ".jpeg", ".png", ".heic", ".webp"):
                    pics.append(os.path.join(dp, f))
            elif ext in VID:
                videos += 1
            else:
                continue
            try:
                size += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    subs = []
    for d in sorted(os.listdir(source)):
        p = os.path.join(source, d)
        if os.path.isdir(p) and not d.startswith(".") and not d.endswith(" (sorted)"):
            n = media_count(p)
            if n:
                subs.append({"name": d, "files": n, "takeout": looks_takeout(p)})
    shutil.rmtree(PEEK, ignore_errors=True)
    os.makedirs(PEEK)
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
    out, stamp = [], int(time.time())
    for i, p in enumerate(random.Random(3).sample(pics, min(60, len(pics)))):
        try:
            with Image.open(p) as im:
                im.draft("RGB", (160, 160))
                im = ImageOps.exif_transpose(im).convert("RGB")
                s = min(im.size)
                im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2)).resize((64, 64))
                im.save(os.path.join(PEEK, f"{i}.jpg"), quality=70)
                out.append(f"peek/{i}.jpg?{stamp}")
        except Exception:
            pass
    return {"source": source, "photos": photos, "videos": videos, "bytes": size, "previews": out,
            "suggested_dest": source.rstrip("/") + " (sorted)", "subfolders": subs[:30],
            "accounts_likely": len(subs) >= 2 and sum(s["takeout"] for s in subs) >= 2}


def open_path(path, reveal=False):
    if sys.platform == "darwin":  # Finder only shows it: a folder named like an app is never launched
        subprocess.run(["open", "-R", path] if reveal else ["open", "-a", "Finder", path])
    elif sys.platform.startswith("win"):
        subprocess.run(["explorer", "/select," + path] if reveal else ["explorer", path])
    else:
        subprocess.run(["xdg-open", os.path.dirname(path) if reveal else path])


def pick_folder(prompt):
    """Native macOS folder picker, shown in front of the browser."""
    if sys.platform != "darwin":
        return None
    prompt = re.sub(r'["\\]', "'", str(prompt))[:120]
    script_ = ('on run argv\n tell application (path to frontmost application as text)\n'
               '  POSIX path of (choose folder with prompt (item 1 of argv))\n end tell\nend run')
    r = subprocess.run(["osascript", "-e", script_, prompt], capture_output=True, text=True)
    return r.stdout.strip().rstrip("/") or None


def check_categories(cats):
    if not isinstance(cats, list) or not 2 <= len(cats) <= 40:
        raise ValueError("Keep between 2 and 40 folders.")
    out = []
    for c in cats:
        if not isinstance(c, dict):
            raise ValueError("Bad folder.")
        key, label = str(c.get("key", "")), str(c.get("label", "")).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", key):
            raise ValueError("Bad folder key.")
        if not label or len(label) > 40 or folder_name({"label": label, "key": key}).startswith("_"):
            raise ValueError("Every folder needs a name (up to 40 letters, not starting with _).")
        if folder_name({"label": label, "key": key}).lower() in ("albums", "highlights"):
            raise ValueError(f"“{label}” is used by Snapsift itself. Pick another folder name.")
        if c.get("kind") not in ("photo", "video"):
            raise ValueError("Each folder is for photos or videos.")
        out.append({"key": key, "kind": c["kind"], "label": label, "emoji": str(c.get("emoji") or "")[:8],
                    "rule": str(c.get("rule") or label).strip()[:300]})
    keys = [c["key"] for c in out]
    names = [folder_name(c).lower() for c in out]
    if len(keys) != len(set(keys)) or len(names) != len(set(names)):
        raise ValueError("Two folders have the same name.")
    if not any(c["kind"] == "photo" for c in out) or not any(c["kind"] == "video" for c in out):
        raise ValueError("Keep at least one photo folder and one video folder.")
    return out


KEEP_ON_FORGET = ("google_upload.json", "apple_import.json", "trashed.csv")  # so nothing is uploaded or imported twice


def forget():
    """Delete everything this tool stored about the library (previews, labels, captions, lists).
    Never touches your photos or the sorted copies. Keeps only the records of what was already
    uploaded/imported/trashed (no photo content), and the Google sign-in unless you sign out."""
    if job["running"]:
        raise ValueError("Wait for the current job to finish.")
    keep = {f: open(os.path.join(WORK, f), "rb").read() for f in KEEP_ON_FORGET if os.path.isfile(os.path.join(WORK, f))}
    for d in (DATA, WORK, PEEK):
        if inside(d, HOME):
            shutil.rmtree(d, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    if keep:
        os.makedirs(WORK, exist_ok=True)
        for f, b in keep.items():
            with open(os.path.join(WORK, f), "wb") as fh:
                fh.write(b)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DASH, **k)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        p = urllib.parse.urlparse(self.path).path
        if p.startswith(("/data/", "/peek/", "/api/")) or p.endswith((".js", ".css", ".html")) or p == "/":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def host_ok(self):
        if self.headers.get("Host") in HOSTS:
            return True
        self.send_error(421, "Misdirected request")  # DNS rebinding or a wrong address
        return False

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def translate_path(self, path):
        path = urllib.parse.unquote(urllib.parse.urlsplit(path).path)
        for prefix, base in (("/data/", DATA), ("/peek/", PEEK)):
            if path.startswith(prefix):
                root, rel = base, path[len(prefix):]
                break
        else:
            root, rel = DASH, path
        parts = [p for p in rel.split("/") if p and p not in (".", "..")]
        if any(p.startswith(".") for p in parts):
            return os.path.join(DASH, ".missing")
        full = os.path.join(root, *parts)
        return full if inside(full, root) else os.path.join(DASH, ".missing")

    def list_directory(self, path):
        self.send_error(404)
        return None

    def do_HEAD(self):
        if self.host_ok():
            super().do_HEAD()

    def do_GET(self):
        if not self.host_ok():
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == "/api/state":
                return self.send_json(state())
            if u.path == "/api/labels":
                return self.send_json(live_labels())
            if u.path == "/api/google":
                return self.send_json(quick(script("upload_google.py", "--status")))
            if u.path == "/api/apple":
                if sys.platform != "darwin":
                    return self.send_json({"files": 0, "albums": 0, "unsupported": True})
                return self.send_json(quick(script("export_apple.py", "--dry-run", *(["--include-albums"] if q.get("albums") == ["1"] else []))))
            if u.path == "/api/trash":
                return self.send_json(quick(script("trash_dupes.py", "--list", *(["--near"] if q.get("near") == ["1"] else []))))
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)
        m = re.match(r"^/api/file/(\d+)$", u.path)
        if m:
            return self.send_original(int(m.group(1)))
        m = re.match(r"^/api/highlight/(\d{4})$", u.path)
        if m:  # only a video highlights.py made, inside the sorted folder
            hl = load(os.path.join(DATA, "highlights.json"), {}) or {}
            root = os.path.join(load(os.path.join(DATA, "source.json"), {}).get("sorted") or "/nonexistent", "Highlights")
            want = os.path.join(root, f"Highlights {m.group(1)}.mp4")
            if want in hl.get("files", []) and inside(want, root) and os.path.isfile(want):
                return self.send_file(want, "video/mp4")
            return self.send_error(404)
        if u.path.startswith("/api/"):
            return self.send_json({"error": "not found"}, 404)
        return super().do_GET()

    def send_original(self, i):
        inv = load(os.path.join(DATA, "inventory.json"), [])
        rec = next((r for r in inv if r["id"] == i), None)
        if not rec or not os.path.isfile(rec["path"]):
            return self.send_error(404)
        path = rec["path"]
        if rec["ext"] in (".heic", ".heif", ".tif", ".tiff", ".bmp"):  # browsers can't show these: convert
            from PIL import Image, ImageOps
            try:
                from pillow_heif import register_heif_opener
                register_heif_opener()
            except ImportError:
                pass
            try:
                im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            except Exception:
                return self.send_error(415)
            im.thumbnail((2400, 2400))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=88)
            b = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if rec["ext"] == ".mov":
            ctype = "video/mp4"  # most iPhone .mov files play fine as mp4
        if not ctype.startswith(("image/", "video/")):
            ctype = "application/octet-stream"
        return self.send_file(path, ctype)

    def send_file(self, path, ctype):
        size = os.path.getsize(path)
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if not m or (not m.group(1) and not m.group(2)):
                return self.send_error(416)
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
            else:  # bytes=-500: the last 500 bytes
                start = max(0, size - int(m.group(2)))
            if start > end:
                return self.send_error(416)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def do_POST(self):
        if not self.host_ok():
            return
        if self.headers.get("Origin") not in ORIGINS:
            return self.send_json({"error": "forbidden"}, 403)  # only this page may call the API
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return self.send_json({"error": "expected JSON"}, 415)  # forms from other sites can't send JSON without asking first
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n > MAX_BODY:
            return self.send_json({"error": "too big"}, 413)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json({"error": "bad JSON"}, 400)
        p = urllib.parse.urlparse(self.path).path
        try:
            if p == "/api/sort":
                sort_all(body)
            elif p == "/api/run":
                run_single(str(body.get("step")), body)
            elif p == "/api/stop":
                if job["running"]:
                    job["stop"] = True
                    if job["proc"]:
                        try:
                            os.killpg(job["proc"].pid, signal.SIGTERM)
                        except (ProcessLookupError, PermissionError):
                            pass
            elif p == "/api/peek":
                return self.send_json(peek(str(body.get("source", ""))))
            elif p == "/api/categories":
                if job["running"]:
                    raise ValueError("Wait for sorting to finish before changing folders.")
                cats = check_categories(body.get("categories"))
                save(CATEGORIES, cats)
                save(os.path.join(DATA, "categories.json"), cats)
            elif p == "/api/move":
                cats = {c["key"]: c for c in load(CATEGORIES, [])}
                inv = {r["id"]: r for r in load(os.path.join(DATA, "inventory.json"), [])}
                i, key = body.get("id"), body.get("key")
                if not isinstance(i, int) or i not in inv or key not in cats or cats[key]["kind"] != inv[i]["kind"]:
                    raise ValueError("Can't move that file there.")
                ov = load(OVERRIDES, {})
                labels = load(os.path.join(DATA, "labels.json"), {})
                meta = load(os.path.join(DATA, "meta.json"), {})
                m = meta.setdefault(str(i), {})
                if str(i) not in ov:  # remember how it was, so Undo can put it back exactly
                    m["label_was"], m["review_was"] = labels.get(str(i)), m.get("review")
                ov[str(i)] = key
                save(OVERRIDES, ov)
                labels[str(i)] = key
                save(os.path.join(DATA, "labels.json"), labels)
                if m.get("review") != "dupe":
                    m["review"] = None
                save(os.path.join(DATA, "meta.json"), meta)
            elif p == "/api/unmove":
                i = body.get("id")
                ov = load(OVERRIDES, {})
                if not isinstance(i, int) or str(i) not in ov:
                    raise ValueError("Nothing to undo for that file.")
                del ov[str(i)]
                save(OVERRIDES, ov)
                meta = load(os.path.join(DATA, "meta.json"), {})
                m = meta.get(str(i), {})
                labels = load(os.path.join(DATA, "labels.json"), {})
                if m.get("label_was"):
                    labels[str(i)] = m["label_was"]
                    save(os.path.join(DATA, "labels.json"), labels)
                if "review_was" in m:
                    m["review"] = m.pop("review_was")
                m.pop("label_was", None)
                save(os.path.join(DATA, "meta.json"), meta)
            elif p == "/api/main_account":
                acct = body.get("account")
                inv = load(os.path.join(DATA, "inventory.json"), [])
                if acct is not None and acct not in {r.get("account") for r in inv}:
                    raise ValueError("Unknown account.")
                info = load(os.path.join(DATA, "source.json"), {})
                info["main_account"] = acct
                save(os.path.join(DATA, "source.json"), info)
                if info.get("sorted"):
                    run_single("rebuild", {})
            elif p == "/api/open":
                self.open_for(body)
            elif p == "/api/pick":
                return self.send_json({"path": pick_folder(body.get("prompt") or "Choose the folder with your photos")})
            elif p == "/api/forget":
                forget()
            elif p == "/api/google_logout":  # also revokes the access at Google
                subprocess.run([PY, *script("upload_google.py", "--logout")], capture_output=True, timeout=60, cwd=ROOT, stdin=subprocess.DEVNULL)
            else:
                return self.send_json({"error": "not found"}, 404)
        except Exception as e:
            return self.send_json({"error": str(e)}, 400)
        return self.send_json(state())

    def open_for(self, body):
        """Reveal an original in Finder, or open a folder of the sorted copies. Never runs a file."""
        src = load(os.path.join(DATA, "source.json"), {})
        if body.get("id") is not None:
            rec = next((r for r in load(os.path.join(DATA, "inventory.json"), []) if r["id"] == body["id"]), None)
            if not rec or not os.path.exists(rec["path"]):
                raise ValueError("That file isn't there any more.")
            return open_path(rec["path"], reveal=True)
        root = src.get("sorted")
        if not root or not os.path.isdir(root):
            raise ValueError("Sort first, then the folders can be opened.")
        sub = body.get("folder")
        if sub:
            cats = {c["key"]: c for c in load(CATEGORIES, [])}
            special = {"_dupes": "_Review/Duplicates", "_private": "_Review/Private", "_junk": "_Review/Junk",
                       "_unsure": "_Review/Not sure", "_albums": "Albums", "_highlights": "Highlights", "_delete": "_Review/Delete lists"}
            rel = special.get(sub) or (folder_name(cats[sub]) if sub in cats else None)
            if rel is None:
                raise ValueError("Unknown folder.")
            path = os.path.join(root, rel)
            if not inside(path, root) or not os.path.isdir(path):
                path = root
        else:
            path = root
        open_path(path, reveal=False)


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    ThreadingHTTPServer.request_queue_size = 128  # the page loads hundreds of thumbnails at once
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    srv.daemon_threads = True
    print(f"Snapsift running at http://127.0.0.1:{PORT}  (Ctrl+C to stop)", flush=True)
    srv.serve_forever()
