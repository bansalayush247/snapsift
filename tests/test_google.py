"""Google Photos upload against a fake Google (no network): sign-in with PKCE + state, token file
permissions, one album per folder, trip albums, location removed, resumable, retries on 503."""
import base64, hashlib, http.server, io, json, os, shutil, stat, subprocess, sys, tempfile, threading, unittest
import urllib.parse, urllib.request

import piexif

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import make_library  # noqa: E402

TMP = tempfile.mkdtemp(prefix="snapsift-g-")
HOME = os.path.join(TMP, "home")
SEEN = {"uploads": [], "albums": [], "created": 0, "added": [], "fail_next_upload": True, "challenge": None}


class FakeGoogle(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj, code=200, raw=None):
        b = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/userinfo"):
            return self.reply({"email": "tester@example.com"})
        self.reply({}, 404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        p = self.path
        if p == "/revoke":
            SEEN["revoked"] = urllib.parse.parse_qs(body.decode())["token"][0]
            return self.reply({})
        if p == "/token":
            f = urllib.parse.parse_qs(body.decode())
            if f["grant_type"][0] == "authorization_code":
                v = f["code_verifier"][0]
                ok = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode() == SEEN["challenge"]
                if not ok or f["code"][0] != "good-code":
                    return self.reply({"error": "invalid_grant"}, 400)
                return self.reply({"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600})
            return self.reply({"access_token": "at-2", "expires_in": 3600})
        if self.headers.get("Authorization", "")[:9] != "Bearer at":
            return self.reply({"error": "unauthenticated"}, 401)
        if p == "/v1/albums":
            SEEN["albums"].append(json.loads(body)["album"]["title"])
            return self.reply({"id": f"alb{len(SEEN['albums'])}"})
        if p == "/v1/uploads":
            if SEEN["fail_next_upload"]:
                SEEN["fail_next_upload"] = False
                return self.reply({"error": "busy"}, 503)
            SEEN["uploads"].append((self.headers.get("X-Goog-Upload-Content-Type"), body))
            return self.reply(None, raw=f"tok{len(SEEN['uploads'])}".encode())
        if p == "/v1/mediaItems:batchCreate":
            items = json.loads(body)["newMediaItems"]
            SEEN["created"] += len(items)
            return self.reply({"newMediaItemResults": [{"uploadToken": i["simpleMediaItem"]["uploadToken"],
                                                        "mediaItem": {"id": "mi-" + i["simpleMediaItem"]["uploadToken"]}} for i in items]})
        if p.endswith(":batchAddMediaItems"):
            SEEN["added"].append(json.loads(body)["mediaItemIds"])
            return self.reply({})
        self.reply({}, 404)


def setUpModule():
    global G, srv
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGoogle)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    os.environ.update(SNAPSIFT_HOME=HOME, SNAPSIFT_GOOGLE_API=base, SNAPSIFT_GOOGLE_TOKEN=base + "/token",
                      SNAPSIFT_GOOGLE_AUTH=base + "/auth", SNAPSIFT_GOOGLE_USERINFO=base + "/userinfo", SNAPSIFT_GOOGLE_REVOKE=base + "/revoke",
                      SNAPSIFT_CLAUDE=os.path.join(ROOT, "tests", "fake_claude.py"))
    os.environ.pop("FAKE_CLAUDE_FAIL_ONCE", None)
    lib = make_library.build(os.path.join(TMP, "lib"))
    for s, *a in (("scan.py", lib, "--accounts"), ("dupes.py",), ("label_claude.py",), ("events.py",), ("apply.py", os.path.join(TMP, "out"))):
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", s), *a], check=True, capture_output=True)
    os.makedirs(os.path.join(HOME, "secrets"), exist_ok=True)
    with open(os.path.join(HOME, "secrets", "google_client.json"), "w") as f:
        json.dump({"installed": {"client_id": "cid.apps.googleusercontent.com", "client_secret": "csecret"}}, f)
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import upload_google
    G = upload_google


def tearDownModule():
    srv.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)


class Google(unittest.TestCase):
    def test_1_login(self):
        results = {}

        def browser(url):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            results["q"] = q
            SEEN["challenge"] = q["code_challenge"][0]
            redirect = q["redirect_uri"][0]

            def go():
                try:  # a forged redirect with the wrong state is refused
                    urllib.request.urlopen(redirect + "?code=evil&state=wrong", timeout=5)
                except urllib.error.HTTPError as e:
                    results["forged"] = e.code
                urllib.request.urlopen(redirect + "?" + urllib.parse.urlencode({"code": "good-code", "state": q["state"][0]}), timeout=5)
            threading.Thread(target=go, daemon=True).start()

        G.webbrowser.open = browser
        G.login(open_browser=True, timeout=20)
        q = results["q"]
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertTrue(q["redirect_uri"][0].startswith("http://127.0.0.1:"))
        self.assertEqual(q["scope"][0].split(), ["https://www.googleapis.com/auth/photoslibrary.appendonly", "openid", "email"])
        self.assertEqual(results["forged"], 400)
        tok = os.path.join(HOME, "secrets", "google_token.json")
        self.assertEqual(stat.S_IMODE(os.stat(tok).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(tok)).st_mode) & 0o077, 0)
        self.assertEqual(G.status()["email"], "tester@example.com")

    def test_2_upload(self):
        code = G.upload(strip=True, include_albums=True)
        self.assertEqual(code, 0)
        plan = G.plan(True)
        self.assertEqual(SEEN["created"], len(plan))
        self.assertEqual(len(SEEN["uploads"]), len(plan))
        self.assertFalse(any(t.startswith("_Review") for t in SEEN["albums"]))
        self.assertIn("Food & drinks".replace("&", "and"), SEEN["albums"])
        self.assertTrue(any(t.startswith("Trip") for t in SEEN["albums"]))   # trips become albums too
        self.assertTrue(SEEN["added"])
        for mime, data in SEEN["uploads"]:
            if mime == "image/jpeg":
                self.assertFalse(piexif.load(data)["GPS"], "location was uploaded")
        # one of the uploads still carries its date
        dated = [d for m, d in SEEN["uploads"] if m == "image/jpeg" and piexif.load(d)["Exif"].get(piexif.ExifIFD.DateTimeOriginal)]
        self.assertTrue(dated)

    def test_2b_xmp_location_is_removed(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), "red").save(buf, "JPEG")
        jpg = buf.getvalue()
        xmp = (b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta><rdf:Description exif:GPSLatitude=\"28,36.8N\" "
               b"exif:GPSLongitude=\"77,12.5E\"/></x:xmpmeta>")
        seg = b"\xff\xe1" + (len(xmp) + 2).to_bytes(2, "big") + xmp
        with_xmp = jpg[:2] + seg + jpg[2:]
        exif = piexif.dump({"0th": {}, "Exif": {}, "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: ((28, 1), (36, 1), (0, 1))}, "1st": {}, "thumbnail": None})
        out = io.BytesIO()
        piexif.insert(exif, with_xmp, out)
        p = os.path.join(TMP, "gps.jpg")
        with open(p, "wb") as f:
            f.write(out.getvalue())
        data, mime = G.without_location({"path": p, "ext": ".jpg", "kind": "photo"})
        self.assertNotIn(b"GPSLatitude", data)
        self.assertFalse(piexif.load(data)["GPS"])
        Image.open(io.BytesIO(data)).load()  # still a valid picture

    def test_3_resumes_without_duplicates(self):
        n = len(SEEN["uploads"])
        G.upload(strip=True, include_albums=True)
        self.assertEqual(len(SEEN["uploads"]), n)
        self.assertEqual(G.status()["left"], 0)

    def test_4_logout_keeps_upload_record(self):
        G.main(["--logout"])
        self.assertEqual(SEEN.get("revoked"), "rt-1")   # access withdrawn at Google too
        self.assertFalse(os.path.exists(os.path.join(HOME, "secrets", "google_token.json")))
        self.assertTrue(os.path.exists(os.path.join(HOME, "work", "google_upload.json")))


if __name__ == "__main__":
    unittest.main()
