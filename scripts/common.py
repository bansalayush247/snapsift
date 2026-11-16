"""Shared paths and helpers. Everything the tool writes lives inside this repo:
  dashboard/data/   inventory, thumbnails, labels (what the dashboard reads)
  work/             contact sheets and raw labels (scratch)
  secrets/          Google sign-in tokens (only if you use Google Photos upload)
Your original photos are only ever read, never changed.

SNAPSIFT_HOME moves all of that somewhere else (the tests use it so they never touch your library).
"""
import glob, json, os, re, shutil, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.abspath(os.environ.get("SNAPSIFT_HOME") or ROOT)
DATA = os.path.join(HOME, "dashboard", "data")
THUMBS = os.path.join(DATA, "thumbs")
MINI = os.path.join(DATA, "mini")
WORK = os.path.join(HOME, "work")
SECRETS = os.path.join(HOME, "secrets")
LABELS = os.path.join(WORK, "labels")      # Claude writes one JSON per batch here
JEV_OUT = os.path.join(WORK, "jev.json")   # Jev labels (optional)
OVERRIDES = os.path.join(WORK, "overrides.json")
# your folders live in config/ (never committed: names and rules can be personal, like kids' names);
# the categories.json in the repo is only the starting template
CATEGORIES = os.environ.get("SNAPSIFT_CATEGORIES") or os.path.join(HOME, "config", "categories.json")
if not os.path.exists(CATEGORIES):
    os.makedirs(os.path.dirname(CATEGORIES), exist_ok=True)
    shutil.copy(os.path.join(ROOT, "categories.json"), CATEGORIES)

IMG = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VID = {".mov", ".mp4", ".m4v", ".3gp", ".avi", ".mkv", ".webm"}
MODELS = ("haiku", "sonnet", "opus")
REVIEW = {"dupe": ("_Review", "Duplicates"), "private": ("_Review", "Private"),
          "junk": ("_Review", "Junk"), "unsure": ("_Review", "Not sure")}


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def save(path, obj):
    """Write atomically, so the dashboard never reads half a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def categories():
    cats = load(CATEGORIES)
    keys = [c["key"] for c in cats]
    assert len(keys) == len(set(keys)), "categories.json has duplicate keys"
    for kind in ("photo", "video"):
        assert any(c["kind"] == kind for c in cats), f"categories.json needs at least one {kind} folder"
    return cats


def safe_name(s, fallback="Untitled", limit=80):
    """A folder or file name that can't escape its parent folder: no slashes, no leading dots,
    no control characters. Used for anything that came from a person or a model."""
    s = re.sub(r"[\x00-\x1f\x7f/\\:]+", "-", str(s or "")).replace("&", "and")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s.\-]+|[\s.]+$", "", s)  # no hidden names, no "..", nothing Windows can't open
    return s[:limit].rstrip() or fallback


def folder_name(cat):
    return safe_name(cat["label"], fallback=cat["key"])


def inside(path, root):
    """True when path (after resolving symlinks and ..) is root or inside it."""
    p, r = os.path.realpath(path), os.path.realpath(root)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def options():
    return load(os.path.join(DATA, "source.json"), {}).get("options", {})


# ---------- Claude Code ----------

def _version(path):
    m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", path)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def find_claude():
    """The `claude` command: on PATH, or the copy inside the VS Code / Cursor extension
    (people who only use Claude Code inside their editor have no `claude` on PATH)."""
    env = os.environ.get("SNAPSIFT_CLAUDE")
    if env:
        return env if os.access(env, os.X_OK) else None
    found = shutil.which("claude")
    if found:
        return found
    home = os.path.expanduser("~")
    for p in (f"{home}/.local/bin/claude", f"{home}/.claude/local/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.access(p, os.X_OK):
            return p
    bundled = []
    for ext_dir in (".vscode/extensions", ".vscode-insiders/extensions", ".cursor/extensions", ".windsurf/extensions"):
        bundled += glob.glob(os.path.join(home, ext_dir, "anthropic.claude-code-*", "resources", "native-binary", "claude"))
    bundled = [p for p in bundled if os.access(p, os.X_OK)]
    return max(bundled, key=_version) if bundled else None


def private_dir():
    """A fresh folder only you can open (0700), outside this repo, for contact sheets Claude reads.
    Outside the repo so Claude doesn't pick up the repo's CLAUDE.md or anything else here."""
    return tempfile.mkdtemp(prefix="snapsift-")


def ask_claude(prompt, cwd=None, model="sonnet", read=True, timeout=900):
    """Run Claude Code headless and return (text, cost, process). Locked down: the only tool it gets
    is Read (or none), only inside `cwd`, no MCP servers, no user settings or hooks, no saved session.
    Photos can contain text that tries to give instructions, so Claude must not be able to do anything
    except look at the contact sheets it was handed. cwd should be a private_dir(); None makes an
    empty one for the call."""
    if cwd is None:
        tmp = private_dir()
        try:
            return ask_claude(prompt, tmp, model, read, timeout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    claude = find_claude()
    if not claude:
        raise RuntimeError("The `claude` command was not found. Install Claude Code from claude.com/claude-code.")
    if model not in MODELS:
        model = "sonnet"
    cmd = [claude, "-p", prompt, "--model", model, "--tools", "Read" if read else "",
           "--strict-mcp-config", "--setting-sources", "project", "--no-session-persistence",
           "--permission-mode", "default", "--output-format", "json"]
    if read:
        cmd += ["--allowedTools", "Read(./**)"]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        res = {"result": r.stdout or r.stderr}
    return str(res.get("result", "")), res.get("total_cost_usd", 0) or 0, r


def json_in(text):
    """The first JSON object in a model's reply (it sometimes adds words or ``` fences)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def progress(n, total):
    print(f"PROGRESS {n} {total}", flush=True)


def now():
    return time.time()


# ---------- labels ----------

def read_labels():
    """Every Claude answer so far, {id: {"k": folder key, "c": caption, "f": flags}}.
    Later files win, so a second look overrides the first. Flags: j junk, s private, u not sure."""
    out = {}
    for f in sorted(glob.glob(os.path.join(LABELS, "*.json"))):
        for k, v in (load(f, {}) or {}).items():
            if isinstance(v, str):
                v = {"k": v}
            if isinstance(v, dict) and isinstance(v.get("k"), str):
                out[str(k)] = {"k": v["k"], "c": str(v.get("c", ""))[:200], "f": "".join(sorted(set(str(v.get("f", ""))) & set("jsu"))),
                               **({"r": 1} if v.get("r") else {})}
    return out


# ---------- places ----------

def km(a, b):
    from math import asin, cos, radians, sin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * asin(min(1, sqrt(h)))


def home_of(recs):
    """Where most located photos were taken (a 0.5 degree cell, about 50 km). Never leaves this computer."""
    cells = {}
    for r in recs:
        g = r.get("geo")
        if g:
            c = (round(g[0] * 2) / 2, round(g[1] * 2) / 2)
            cells.setdefault(c, []).append(g)
    if not cells:
        return None
    pts = max(cells.values(), key=len)
    return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]


AWAY_KM = 100
