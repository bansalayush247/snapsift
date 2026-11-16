"""The dashboard server: a full sort through the API like the page does it, plus the security rules
(host check, origin check, no listings, no path tricks, input validation, safe Finder opening)."""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import make_library  # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="snapsift-srv-")
        cls.lib = make_library.build(os.path.join(cls.tmp, "lib"))
        cls.home = os.path.join(cls.tmp, "home")
        cls.port = free_port()
        cls.host = f"127.0.0.1:{cls.port}"
        env = dict(os.environ, SNAPSIFT_HOME=cls.home, SNAPSIFT_CLAUDE=os.path.join(ROOT, "tests", "fake_claude.py"), PORT=str(cls.port))
        env.pop("FAKE_CLAUDE_FAIL_ONCE", None)
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "scripts", "server.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, host=None, origin="default", ctype="application/json", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": self.host if host is None else host}
        if origin == "default":
            origin = f"http://{self.host}" if method == "POST" else None
        if origin:
            h["Origin"] = origin
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h["Content-Type"] = ctype
        h.update(headers or {})
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def api(self, path, body=None):
        s, _, b = self.req("POST" if body is not None else "GET", path, body)
        return s, json.loads(b or b"{}")

    def wait_job(self, timeout=300):
        end = time.time() + timeout
        while time.time() < end:
            _, st = self.api("/api/state")
            if not st["job"]["running"]:
                return st
            time.sleep(0.5)
        self.fail("job didn't finish")

    # ---------- a full sort through the API ----------

    def test_01_sort_through_api(self):
        s, peek = self.api("/api/peek", {"source": self.lib})
        self.assertEqual(s, 200)
        self.assertTrue(peek["accounts_likely"])
        self.assertEqual({x["name"] for x in peek["subfolders"]}, {"personal", "work"})
        dest = os.path.join(self.tmp, "out")
        s, st = self.api("/api/sort", {"source": self.lib, "dest": dest, "accounts": True, "model": "opus", "layout": "month"})
        self.assertEqual(s, 200, st)
        st = self.wait_job()
        self.assertEqual(st["job"]["code"], 0, st["job"]["log"])
        self.assertEqual(st["accounts"], ["personal", "work"])
        self.assertEqual(st["options"]["model"], "opus")
        self.assertTrue(st["steps"]["report"])
        self.assertTrue(os.path.isdir(os.path.join(dest, "Food and drinks", "2023-06")))

    def test_02_main_account_rebuild(self):
        s, st = self.api("/api/main_account", {"account": "personal"})
        self.assertEqual(s, 200, st)
        st = self.wait_job()
        self.assertEqual(st["job"]["code"], 0, st["job"]["log"])
        self.assertEqual(st["main_account"], "personal")
        s, _ = self.api("/api/main_account", {"account": "../../etc"})
        self.assertEqual(s, 400)

    def test_03_move_validation(self):
        inv = json.load(open(os.path.join(self.home, "dashboard", "data", "inventory.json")))
        photo = next(r for r in inv if r["kind"] == "photo")
        self.assertEqual(self.api("/api/move", {"id": photo["id"], "key": "food"})[0], 200)
        self.assertEqual(self.api("/api/move", {"id": photo["id"], "key": "vclips"})[0], 400)   # a photo can't go in a video folder
        self.assertEqual(self.api("/api/move", {"id": photo["id"], "key": "../x"})[0], 400)
        self.assertEqual(self.api("/api/move", {"id": "1; rm -rf /", "key": "food"})[0], 400)

    def test_04_file_serving(self):
        s, h, b = self.req("GET", "/api/file/0")
        self.assertEqual(s, 200)
        self.assertTrue(h["Content-Type"].startswith(("image/", "video/")))
        self.assertEqual(self.req("GET", "/api/file/99999")[0], 404)
        self.assertEqual(self.req("GET", "/api/file/0", headers={"Range": "bytes=50-10"})[0], 416)
        s, h, b = self.req("GET", "/api/file/0", headers={"Range": "bytes=-10"})
        self.assertEqual((s, len(b)), (206, 10))

    # ---------- security ----------

    def test_10_dns_rebinding_blocked(self):
        for host in ("evil.example:%d" % self.port, "127.0.0.1", "localhost.evil.example", ""):
            self.assertEqual(self.req("GET", "/api/state", host=host)[0], 421, host)
            self.assertEqual(self.req("GET", "/api/file/0", host=host)[0], 421, host)
        self.assertEqual(self.req("GET", "/api/state", host=f"localhost:{self.port}")[0], 200)

    def test_11_cross_site_posts_blocked(self):
        self.assertEqual(self.req("POST", "/api/forget", {}, origin="https://evil.example")[0], 403)
        self.assertEqual(self.req("POST", "/api/forget", {}, origin=None)[0], 403)
        self.assertEqual(self.req("POST", "/api/forget", {}, origin="null")[0], 403)
        self.assertEqual(self.req("POST", "/api/forget", b"{}", ctype="text/plain")[0], 415)
        # a huge body is refused from its Content-Length alone, before it is read
        sock = socket.create_connection(("127.0.0.1", self.port))
        sock.sendall((f"POST /api/forget HTTP/1.1\r\nHost: {self.host}\r\nOrigin: http://{self.host}\r\n"
                      f"Content-Type: application/json\r\nContent-Length: {2 << 20}\r\n\r\n").encode())
        self.assertIn(b" 413 ", sock.recv(200))
        sock.close()
        self.assertEqual(self.req("POST", "/api/forget", b"[1,2]")[0], 400)

    def test_12_security_headers(self):
        s, h, _ = self.req("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertEqual(h["Cross-Origin-Resource-Policy"], "same-origin")

    def test_13_no_listing_no_traversal(self):
        for path in ("/data/", "/data/thumbs/", "/peek/", "/data/../../scripts/server.py", "/%2e%2e/scripts/server.py",
                     "/data/%2e%2e/%2e%2e/%2e%2e/etc/passwd", "/.git/config", "/..%2f..%2fREADME.md", "/data/.hidden"):
            s, _, b = self.req("GET", path)
            self.assertEqual(s, 404, path)
        self.assertEqual(self.req("GET", "/data/thumbs/0.jpg")[0], 200)

    def test_14_open_cannot_escape_or_run(self):
        for folder in ("../../Applications/Calculator.app", "/Applications", "food/../../..", "_nope"):
            self.assertEqual(self.api("/api/open", {"folder": folder})[0], 400, folder)
        self.assertEqual(self.api("/api/open", {"id": 99999})[0], 400)

    def test_15_category_validation(self):
        with open(os.path.join(self.home, "config", "categories.json")) as f:
            good = json.load(f)
        bad = [
            [dict(good[0], key="../evil")] + good[1:],
            [dict(good[0], label="")] + good[1:],
            [dict(good[0], label="_Review")] + good[1:],
            [dict(good[0], label="x" * 41)] + good[1:],
            [dict(good[0], kind="script")] + good[1:],
            [c for c in good if c["kind"] == "photo"],
            [dict(good[0])] + [dict(good[1], label=good[0]["label"])] + good[2:],
            [dict(good[0], label="Albums")] + good[1:],
            [dict(good[0], label="highlights")] + good[1:],
        ]
        for cats in bad:
            self.assertEqual(self.api("/api/categories", {"categories": cats})[0], 400)
        s, st = self.api("/api/categories", {"categories": [dict(good[0], label="../../Food")] + good[1:]})
        self.assertEqual(s, 200)  # allowed, but the folder name is made safe
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from common import folder_name
        self.assertEqual(folder_name(st["categories"][0]), "Food")
        self.api("/api/categories", {"categories": good})

    def test_16_jobs_validate(self):
        self.assertEqual(self.api("/api/run", {"step": "trash", "confirm": "all"})[0], 400)
        self.assertEqual(self.api("/api/run", {"step": "rm -rf"})[0], 400)
        self.assertEqual(self.api("/api/sort", {"source": self.lib, "dest": os.path.join(self.lib, "inside")})[0], 400)
        self.assertEqual(self.api("/api/sort", {"source": self.lib, "dest": os.path.expanduser("~")})[0], 400)
        self.assertEqual(self.api("/api/sort", {"source": self.lib, "dest": os.path.dirname(self.lib)})[0], 400)

    def test_99_forget(self):
        before = sorted(os.listdir(self.lib))
        os.makedirs(os.path.join(self.home, "work"), exist_ok=True)
        with open(os.path.join(self.home, "work", "google_upload.json"), "w") as f:
            f.write('{"items": {"1": "x"}}')
        s, st = self.api("/api/forget", {})
        self.assertEqual(s, 200)
        self.assertEqual(st["files"], 0)
        self.assertEqual(os.listdir(os.path.join(self.home, "work")), ["google_upload.json"])  # nothing re-uploads twice
        self.assertEqual(sorted(os.listdir(self.lib)), before)


if __name__ == "__main__":
    unittest.main()
