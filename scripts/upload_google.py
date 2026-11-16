"""Upload the sorted library to ONE Google Photos account, one album per folder.

  python scripts/upload_google.py --status          # set up? signed in? how much would be uploaded
  python scripts/upload_google.py --login           # sign in in your browser (once)
  python scripts/upload_google.py [--strip-location] [--include-albums]
  python scripts/upload_google.py --logout          # forget the sign-in

One-time setup (Google requires every app to have its own key):
  1. console.cloud.google.com > new project > APIs & Services > Library > enable "Photos Library API"
  2. OAuth consent screen: External, add yourself as a test user
  3. Credentials > Create credentials > OAuth client ID > Desktop app > Download JSON
  4. Save it as secrets/google_client.json in this folder (it is never committed)

What it can do in your account: only ADD photos and create albums (scope photoslibrary.appendonly).
It cannot see, change or delete anything already in your Google Photos.
Uploads the sorted copies (with fixed dates), never the _Review folders. Resumable: run it again and
it skips what is already up. --strip-location removes GPS before upload (JPEGs losslessly; other
photos are re-saved as high-quality JPEG; videos keep their date but lose location).
"""
import argparse, base64, csv, hashlib, http.server, io, json, os, secrets, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.parse, urllib.request, webbrowser

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, SECRETS, WORK, load, progress, save

API = os.environ.get("SNAPSIFT_GOOGLE_API", "https://photoslibrary.googleapis.com")
TOKEN_URL = os.environ.get("SNAPSIFT_GOOGLE_TOKEN", "https://oauth2.googleapis.com/token")
AUTH_URL = os.environ.get("SNAPSIFT_GOOGLE_AUTH", "https://accounts.google.com/o/oauth2/v2/auth")
USERINFO = os.environ.get("SNAPSIFT_GOOGLE_USERINFO", "https://openidconnect.googleapis.com/v1/userinfo")
REVOKE = os.environ.get("SNAPSIFT_GOOGLE_REVOKE", "https://oauth2.googleapis.com/revoke")
VIDEO_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi"
SCOPES = "https://www.googleapis.com/auth/photoslibrary.appendonly openid email"
CLIENT = os.path.join(SECRETS, "google_client.json")
TOKEN = os.path.join(SECRETS, "google_token.json")
STATE = os.path.join(WORK, "google_upload.json")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".heic": "image/heic", ".heif": "image/heif",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff",
        ".mov": "video/quicktime", ".mp4": "video/mp4", ".m4v": "video/x-m4v", ".3gp": "video/3gpp",
        ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".webm": "video/webm"}


def write_private(path, obj):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(path), 0o700)  # also when you made the folder yourself to put the client file in
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)


def client():
    j = load(CLIENT)
    if not j:
        return None
    c = j.get("installed") or j.get("web") or j
    return {"id": c.get("client_id"), "secret": c.get("client_secret", "")} if c.get("client_id") else None


def post_form(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


# ---------- sign in ----------

def login(open_browser=True, timeout=300):
    c = client()
    if not c:
        sys.exit("Google isn't set up yet: save your OAuth client file as secrets/google_client.json (see the top of this script).")
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = q.get("state", [""])[0] == state and "code" in q
            if ok:
                got["code"] = q["code"][0]
            elif q.get("error"):
                got["error"] = q["error"][0]
            body = (b"<!doctype html><meta charset=utf-8><title>Snapsift</title><body style='font:16px system-ui;padding:40px'>"
                    + (b"Signed in. You can close this tab and go back to Snapsift." if ok else b"Sign-in didn't work. Go back to Snapsift and try again."))
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": c["id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPES, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent select_account"})
    print("Opening Google sign-in in your browser...", flush=True)
    print(f"If it doesn't open, go to: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    srv.timeout = 2
    end = time.time() + timeout
    while "code" not in got and "error" not in got and time.time() < end:
        srv.handle_request()
    srv.server_close()
    if "code" not in got:
        sys.exit(f"Sign-in didn't finish ({got.get('error', 'timed out')}).")
    tok = post_form(TOKEN_URL, {"code": got["code"], "client_id": c["id"], "client_secret": c["secret"], "redirect_uri": redirect,
                                "grant_type": "authorization_code", "code_verifier": verifier})
    if not tok.get("refresh_token"):
        sys.exit("Google didn't return a sign-in that lasts. Remove Snapsift's access at myaccount.google.com/permissions and try again.")
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    tok["email"] = email_of(tok["access_token"])
    write_private(TOKEN, {k: tok[k] for k in ("refresh_token", "access_token", "expires_at", "email") if k in tok})
    print(f"Signed in as {tok['email'] or 'your Google account'}.", flush=True)


def email_of(access):
    try:
        req = urllib.request.Request(USERINFO, headers={"Authorization": "Bearer " + access})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("email", "")
    except Exception:
        return ""


def access_token():
    tok = load(TOKEN)
    if not tok:
        sys.exit("Not signed in to Google yet.")
    if tok.get("access_token") and tok.get("expires_at", 0) > time.time():
        return tok["access_token"]
    c = client()
    if not c:
        sys.exit("The Google client file secrets/google_client.json is missing.")
    try:
        new = post_form(TOKEN_URL, {"refresh_token": tok["refresh_token"], "client_id": c["id"], "client_secret": c["secret"],
                                    "grant_type": "refresh_token"})
    except urllib.error.HTTPError as e:
        sys.exit(f"Google sign-in expired ({e.code}). Sign in again.")
    tok.update(access_token=new["access_token"], expires_at=time.time() + new.get("expires_in", 3600) - 60)
    write_private(TOKEN, tok)
    return tok["access_token"]


# ---------- what to upload ----------

def plan(include_albums):
    """[(id, path of the sorted copy, category album, [event albums])] from sorted.csv."""
    src = load(os.path.join(DATA, "source.json"), {})
    dest = src.get("sorted")
    if not dest or not os.path.exists(os.path.join(dest, "sorted.csv")):
        sys.exit("Sort first, then upload the sorted folders.")
    by_path = {r["path"]: r for r in load(os.path.join(DATA, "inventory.json"), [])}
    items = {}
    with open(os.path.join(dest, "sorted.csv"), newline="") as f:
        for row in csv.DictReader(f):
            r = by_path.get(row["original_path"])
            folder = row["folder"].split(os.sep)
            if not r or folder[0] == "_Review":
                continue
            it = items.setdefault(r["id"], {"id": r["id"], "path": None, "album": None, "events": [], "ext": r["ext"], "bytes": r["bytes"],
                                            "taken": r.get("taken"), "kind": r["kind"]})
            if folder[0] == "Albums":
                if include_albums and len(folder) > 1:
                    it["events"].append(folder[1])
                if not it["path"]:
                    it["path"] = os.path.join(dest, row["file"])
            else:
                it["album"] = folder[0]
                it["path"] = os.path.join(dest, row["file"])
    return [it for it in items.values() if it["album"] and it["path"] and os.path.exists(it["path"])]


def status():
    c, tok = client(), load(TOKEN) or {}
    out = {"configured": bool(c), "signed_in": bool(tok.get("refresh_token")), "email": tok.get("email", "")}
    try:
        items = plan(True)
        done = load(STATE, {}).get("items", {})
        left = [i for i in items if str(i["id"]) not in done]
        out.update(files=len(items), left=len(left), bytes=sum(i["bytes"] for i in left),
                   albums=len({i["album"] for i in items}))
    except SystemExit as e:
        out["error"] = str(e)
    return out


# ---------- strip location ----------

XMP_IDS = (b"http://ns.adobe.com/xap/1.0/\x00", b"http://ns.adobe.com/xmp/extension/\x00")


def drop_xmp(data):
    """Remove XMP (APP1) and Photoshop (APP13) blocks from a JPEG, where editors also keep GPS.
    Walks the JPEG markers up to the image data; the picture itself is untouched."""
    if data[:2] != b"\xff\xd8":
        return data
    out, i = bytearray(b"\xff\xd8"), 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: the rest is image data
            break
        if marker in (0x01,) or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        seg = data[i:i + 2 + length]
        body = seg[4:]
        if not ((marker == 0xE1 and body.startswith(XMP_IDS)) or marker == 0xED):
            out += seg
        i += 2 + length
    return bytes(out + data[i:])


def without_location(it):
    """(bytes, mime) of the file to upload, GPS removed."""
    path, ext = it["path"], it["ext"]
    if ext in (".jpg", ".jpeg"):
        import piexif
        data = open(path, "rb").read()
        try:
            ex = piexif.load(data)
        except Exception:
            return data, MIME[ext]
        data = drop_xmp(data)
        if ex.get("GPS"):
            ex["GPS"] = {}
            out = io.BytesIO()
            piexif.insert(piexif.dump(ex), data, out)
            return out.getvalue(), MIME[ext]
        return data, MIME[ext]
    if it["kind"] == "photo":
        from PIL import Image, ImageOps
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
        with Image.open(path) as im:
            ex = im.getexif()
            if 0x8825 in ex:
                del ex[0x8825]
            im = ImageOps.exif_transpose(im).convert("RGB")
            if 0x0112 in ex:
                del ex[0x0112]  # already rotated
            out = io.BytesIO()
            im.save(out, "JPEG", quality=93, exif=ex.tobytes())
        return out.getvalue(), "image/jpeg"
    fd, tmp = tempfile.mkstemp(suffix=ext, dir=WORK)
    os.close(fd)
    try:
        cmd = ["ffmpeg", "-v", "error", "-y", "-format_whitelist", VIDEO_FORMATS, "-i", path, "-map", "0", "-c", "copy", "-map_metadata", "-1"]
        if it.get("taken"):
            cmd += ["-metadata", "creation_time=" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(it["taken"]))]
        r = subprocess.run(cmd + [tmp], capture_output=True, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise RuntimeError("couldn't remove the location from this video")
        return open(tmp, "rb").read(), MIME.get(ext, "video/mp4")
    finally:
        os.remove(tmp)


# ---------- Google Photos API ----------

def call(method, path, token, body=None, data=None, headers=None, tries=5):
    url = path if path.startswith("http") else API + path
    h = {"Authorization": "Bearer " + token}
    h.update(headers or {})
    if body is not None:
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    if hasattr(data, "seek"):  # a file: stream it instead of reading a big video into memory
        h["Content-Length"] = str(os.fstat(data.fileno()).st_size)
    for attempt in range(tries):
        if hasattr(data, "seek"):
            data.seek(0)
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = r.read()
                return raw if headers and headers.get("X-Goog-Upload-Protocol") else json.loads(raw or b"{}")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(min(60, 2 ** attempt * 3))
                continue
            raise RuntimeError(f"Google said {e.code}: {msg}")
        except urllib.error.URLError as e:
            if attempt < tries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"Couldn't reach Google: {e.reason}")


def album_id(title, token, state):
    if title not in state["albums"]:
        state["albums"][title] = call("POST", "/v1/albums", token, {"album": {"title": title[:500]}})["id"]
        save(STATE, state)
    return state["albums"][title]


def upload(strip, include_albums):
    token = access_token()
    who = (load(TOKEN) or {}).get("email", "")
    state = load(STATE, {})
    if state.get("account") != who:  # another account: start fresh for it
        state = {"account": who, "items": {}, "albums": {}, "added": {}}
    items = plan(include_albums)
    todo = [i for i in items if str(i["id"]) not in state["items"]]
    print(f"Uploading {len(todo)} of {len(items)} files to {who or 'Google Photos'}"
          + (", removing location first" if strip else "") + "...", flush=True)
    by_album = {}
    for i in todo:
        by_album.setdefault(i["album"], []).append(i)
    done, failed = 0, []
    for title, group in by_album.items():
        aid = album_id(title, token, state)
        for s in range(0, len(group), 50):  # batchCreate takes up to 50
            chunk, new = group[s:s + 50], []
            for it in chunk:
                try:
                    hdr = {"Content-Type": "application/octet-stream", "X-Goog-Upload-Protocol": "raw"}
                    if strip:
                        data, mime = without_location(it)
                        up = call("POST", "/v1/uploads", token, data=data, headers={**hdr, "X-Goog-Upload-Content-Type": mime})
                    else:
                        with open(it["path"], "rb") as fh:
                            up = call("POST", "/v1/uploads", token, data=fh, headers={
                                **hdr, "X-Goog-Upload-Content-Type": MIME.get(it["ext"], "application/octet-stream")})
                    new.append((it, up.decode()))
                except Exception as e:
                    failed.append(f"{os.path.basename(it['path'])}: {e}")
                token = access_token()
            if new:
                res = call("POST", "/v1/mediaItems:batchCreate", token, {"albumId": aid, "newMediaItems": [
                    {"simpleMediaItem": {"uploadToken": t, "fileName": os.path.basename(it["path"])}} for it, t in new]})
                for (it, _), r in zip(new, res.get("newMediaItemResults", [])):
                    mi = r.get("mediaItem", {}).get("id")
                    if mi:
                        state["items"][str(it["id"])] = mi
                    else:
                        failed.append(f"{os.path.basename(it['path'])}: {r.get('status', {}).get('message', 'not created')}")
                save(STATE, state)
            done += len(chunk)
            progress(done, max(1, len(todo)))
    if include_albums:  # trips and events: add the already uploaded photos to more albums
        events = {}
        for i in items:
            for e in i["events"]:
                if str(i["id"]) in state["items"] and str(i["id"]) not in state["added"].get(e, []):
                    events.setdefault(e, []).append(i)
        for title, group in events.items():
            aid = album_id(title, token, state)
            for s in range(0, len(group), 50):
                chunk = group[s:s + 50]
                call("POST", f"/v1/albums/{urllib.parse.quote(aid)}:batchAddMediaItems", token,
                     {"mediaItemIds": [state["items"][str(i["id"])] for i in chunk]})
                state["added"].setdefault(title, []).extend(str(i["id"]) for i in chunk)
                save(STATE, state)
    progress(1, 1)
    print(f"Done: {len(state['items'])} files in Google Photos, {len(state['albums'])} albums"
          + (f", {len(failed)} failed (run again to retry). First: {failed[0]}" if failed else ""), flush=True)
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--logout", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--strip-location", action="store_true")
    ap.add_argument("--include-albums", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        print(json.dumps(status()))
    elif a.login:
        login(not a.no_browser)
    elif a.logout:
        tok = load(TOKEN) or {}
        revoked = False
        if tok.get("refresh_token"):  # tell Google too, so the access is really gone
            try:
                post_form(REVOKE, {"token": tok["refresh_token"]})
                revoked = True
            except Exception:
                print("Couldn't reach Google to revoke; remove access at myaccount.google.com/permissions.")
        if os.path.exists(TOKEN):  # the upload record stays, so signing in again never uploads twice
            os.remove(TOKEN)
        print("Signed out" + (" and Snapsift's access to your Google Photos was revoked." if revoked else "."))
    else:
        sys.exit(upload(a.strip_location, a.include_albums))


if __name__ == "__main__":
    main()
