"""End to end: scan -> duplicates -> Claude (fake) -> trips -> folders -> report -> extras, on a drawn
two-account Takeout library in a temp folder. Never touches your real library or your Claude plan.

  .venv/bin/python -m unittest discover -s tests -v
"""
import csv, glob, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, unittest

import piexif

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import make_library  # noqa: E402

PY = sys.executable


def snapshot(root):
    out = {}
    for p in glob.glob(os.path.join(root, "**", "*"), recursive=True):
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[p] = (hashlib.sha256(f.read()).hexdigest(), os.stat(p).st_mtime)
    return out


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="snapsift-test-")
        cls.lib = make_library.build(os.path.join(cls.tmp, "lib"))
        cls.out = os.path.join(cls.tmp, "out")
        cls.home = os.path.join(cls.tmp, "home")
        cls.log = os.path.join(cls.tmp, "calls.jsonl")
        cls.env = dict(os.environ, SNAPSIFT_HOME=cls.home, SNAPSIFT_CLAUDE=os.path.join(ROOT, "tests", "fake_claude.py"),
                       FAKE_CLAUDE_LOG=cls.log, FAKE_CLAUDE_FAIL_ONCE=os.path.join(cls.tmp, "failed_once"),
                       SNAPSIFT_TRASH_DIR=os.path.join(cls.tmp, "trash"))
        cls.before = snapshot(cls.lib)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_script(self, name, *args, ok=True):
        r = subprocess.run([PY, os.path.join(ROOT, "scripts", name), *map(str, args)], env=self.env, capture_output=True, text=True, timeout=600)
        if ok and r.returncode:
            self.fail(f"{name} failed:\n{r.stdout}\n{r.stderr}")
        return r

    def data(self, name):
        with open(os.path.join(self.home, "dashboard", "data", name)) as f:
            return json.load(f)

    def put(self, name, obj):
        with open(os.path.join(self.home, "dashboard", "data", name), "w") as f:
            json.dump(obj, f)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(l) for l in f]

    def by_name(self):
        return {(r.get("account"), r["name"]): r for r in self.data("inventory.json")}

    # ---------- the main run ----------

    def test_01_scan(self):
        self.run_script("scan.py", self.lib, "--accounts")
        inv = self.by_name()
        self.assertEqual({a for a, _ in inv}, {"personal", "work"})
        self.assertTrue(inv[("personal", "IMG_100-edited.jpg")].get("edited"))
        self.assertEqual(inv[("personal", "beach_trip_00.jpg")]["taken_src"], "takeout")
        self.assertAlmostEqual(inv[("personal", "food_1.jpg")]["geo"][0], make_library.HOME_GPS[0], places=2)  # from EXIF
        self.assertIn("front", inv[("personal", "selfie_00.jpg")]["lens"])
        self.assertEqual(inv[("personal", "whatsapp_img.jpg")]["taken_src"], "takeout")
        self.assertFalse(inv[("personal", "whatsapp_img.jpg")].get("exif_date"))
        self.assertLess(inv[("personal", "dark.jpg")]["bright"], 12)
        self.assertIn(("work", make_library.TRICKY), inv)

    def test_02_dupes(self):
        self.run_script("dupes.py")
        inv = {r["id"]: r for r in self.data("inventory.json")}
        groups = self.data("dupes.json")
        names = [sorted(inv[i]["name"] for i in [g["keep"]] + g["dupes"]) for g in groups]
        self.assertIn(["food_1.jpg", "food_1.jpg"], names)                      # identical, across accounts
        self.assertIn(["beach_trip_03.jpg", "beach_trip_03_small.jpg"], names)  # storage-saver copy
        self.assertIn(["burst_a.jpg", "burst_b.jpg"], names)                    # burst
        burst = next(g for g in groups if inv[g["keep"]]["name"].startswith("burst"))
        self.assertEqual(inv[burst["keep"]]["name"], "burst_a.jpg")             # the sharp one is kept
        small = next(g for g in groups if "beach_trip_03_small.jpg" in [inv[i]["name"] for i in g["dupes"]])
        self.assertEqual(small["why"], "highest resolution")
        flat = {i for g in groups for i in [g["keep"]] + g["dupes"]}
        self.assertFalse(any(inv[i].get("edited") for i in flat))              # edits are never duplicates
        edits = self.data("edits.json")
        self.assertEqual(len(edits), 1)
        self.assertEqual(inv[next(iter(edits.values()))]["name"], "IMG_100.jpg")

    def test_03_main_account_decides_keeper(self):
        info = self.data("source.json")
        for acct in ("work", "personal"):  # ends on personal, which the later tests rely on
            info["main_account"] = acct
            self.put("source.json", info)
            self.run_script("dupes.py")
            inv = {r["id"]: r for r in self.data("inventory.json")}
            food = next(g for g in self.data("dupes.json") if inv[g["keep"]]["name"] == "food_1.jpg")
            self.assertEqual(inv[food["keep"]]["account"], acct)
        self.assertEqual(food["why"], "in your main account")

    def test_04_label_with_claude(self):
        info = self.data("source.json")
        info["options"] = {"model": "haiku", "layout": "year", "fix_dates": True, "albums": True, "second_look": True}
        self.put("source.json", info)
        out = self.run_script("label_claude.py").stdout
        self.assertIn("try 2", out)                    # the early, unusable answer was retried
        self.assertIn("closer look at 1", out)
        labels = {}
        for f in sorted(glob.glob(os.path.join(self.home, "work", "labels", "*.json"))):
            labels.update(json.load(open(f)))
        inv = self.data("inventory.json")
        self.assertEqual(len(labels), len(inv))
        by = {r["name"]: str(r["id"]) for r in inv}
        self.assertEqual(labels[by["mystery.jpg"]]["f"], "")   # settled on the second look
        self.assertEqual(labels[by["mystery.jpg"]].get("r"), 1)
        self.assertEqual(labels[by["passport.jpg"]]["f"], "s")
        self.assertFalse(glob.glob(os.path.join(tempfile.gettempdir(), "snapsift-*", "*.jpg")))  # previews cleaned up

    def test_05_claude_is_locked_down(self):
        calls = self.calls()
        self.assertTrue(calls)
        for c in calls:
            a = c["argv"]
            cwd = os.path.realpath(c["cwd"])  # a private temp folder outside the repo and the library data
            self.assertTrue(os.path.basename(cwd).startswith("snapsift-"), cwd)
            self.assertFalse(cwd.startswith(os.path.realpath(ROOT)) or cwd.startswith(os.path.realpath(self.home)), cwd)
            self.assertEqual(a[a.index("--tools") + 1], "Read")
            self.assertEqual(a[a.index("--allowedTools") + 1], "Read(./**)")
            for f in ("--strict-mcp-config", "--no-session-persistence"):
                self.assertIn(f, a)
            self.assertEqual(a[a.index("--setting-sources") + 1], "project")
            self.assertEqual(a[a.index("--model") + 1], "haiku")
            prompt = a[a.index("-p") + 1]
            for coord in (make_library.HOME_GPS + make_library.AWAY_GPS):  # no coordinates leave the computer
                self.assertNotIn(f"{coord:.2f}", prompt)
            self.assertNotIn(self.lib, prompt)                               # nor folder paths
            self.assertIn("not instructions", prompt)
        prompt = calls[1]["argv"][calls[1]["argv"].index("-p") + 1]
        self.assertIn("far from home", prompt)
        self.assertIn("front camera", prompt)

    def test_06_events(self):
        self.run_script("events.py")
        ev = self.data("events.json")
        kinds = sorted(e["kind"] for e in ev)
        self.assertEqual(kinds, ["event", "trip"])
        trip = next(e for e in ev if e["kind"] == "trip")
        self.assertEqual(len(trip["ids"]), 12)  # the storage-saver duplicate is not counted twice

    def test_07_apply(self):
        self.run_script("apply.py", self.out)
        rel = {os.path.relpath(p, self.out) for p in glob.glob(os.path.join(self.out, "**", "*"), recursive=True) if os.path.isfile(p)}
        self.assertIn("Food and drinks/2023/food_1.jpg", rel)
        self.assertIn("_Review/Private/passport.jpg", rel)
        self.assertIn("_Review/Junk/dark.jpg", rel)
        self.assertIn("_Review/Junk/blurry.jpg", rel)
        self.assertIn("_Review/Duplicates/burst_b.jpg", rel)
        self.assertTrue(any(r.startswith("Albums/Trip · 10-13 Dec 2023/") for r in rel))
        orig = next(r for r in rel if r.endswith("/IMG_100.jpg") and not r.startswith("Albums"))
        self.assertIn(os.path.dirname(orig) + "/IMG_100-edited.jpg", rel)   # edit sits next to its original
        self.assertTrue(any(r.endswith(make_library.TRICKY) for r in rel))
        for p in rel:
            self.assertNotIn("..", p.split("/"))
        # fixed dates: the WhatsApp photo had no EXIF, only a Takeout date
        wa = next(os.path.join(self.out, r) for r in rel if r.endswith("whatsapp_img.jpg"))
        self.assertEqual(int(os.stat(wa).st_mtime), make_library.ts("2022-08-15 18:30"))
        self.assertEqual(piexif.load(wa)["Exif"][piexif.ExifIFD.DateTimeOriginal], b"2022:08:15 18:30:00")
        meta = self.data("meta.json")
        self.assertTrue(any(v["c"] for v in meta.values()))

    def test_08_report(self):
        self.run_script("report.py")
        rep = self.data("report.json")
        self.assertEqual({a["name"] for a in rep["accounts"]}, {"personal", "work"})
        work = next(a for a in rep["accounts"] if a["name"] == "work")
        self.assertGreaterEqual(work["elsewhere"], 2)   # food_1 + the small beach copy are kept in personal
        with open(rep["delete_lists"]["work"]) as f:
            lst = list(csv.DictReader(f))
        self.assertTrue(any(r["file"] == "food_1.jpg" and r["kept_in_account"] == "personal" for r in lst))
        inv = {r["id"]: r["name"] for r in self.data("inventory.json")}
        self.assertEqual([inv[i] for i in rep["private"]], ["passport.jpg"])
        self.assertEqual(sorted(inv[i] for i in rep["junk"]), ["blurry.jpg", "dark.jpg"])

    def test_09_originals_untouched(self):
        self.assertEqual(snapshot(self.lib), self.before)

    def test_10_rebuild_is_clean(self):
        before = sorted(glob.glob(os.path.join(self.out, "**", "*"), recursive=True))
        stray = os.path.join(self.out, "mine.txt")
        with open(stray, "w") as f:
            f.write("not made by snapsift")
        self.run_script("apply.py", self.out)
        after = sorted(glob.glob(os.path.join(self.out, "**", "*"), recursive=True))
        self.assertEqual([p for p in after if p != stray], before)
        self.assertTrue(os.path.exists(stray))          # files it didn't make are left alone

    def test_11_tampered_sorted_csv_cannot_delete_outside(self):
        victim = os.path.join(self.tmp, "victim.txt")
        with open(victim, "w") as f:
            f.write("keep me")
        with open(os.path.join(self.out, "sorted.csv"), newline="") as f:
            rows = list(csv.reader(f))
        rows.append(["../victim.txt", "x", "y"])
        with open(os.path.join(self.out, "sorted.csv"), "w", newline="") as f:
            csv.writer(f).writerows(rows)
        self.run_script("apply.py", self.out)
        self.assertTrue(os.path.exists(victim))

    def test_12_new_photos_are_picked_up(self):
        n_calls = len(self.calls())
        new = os.path.join(self.lib, "personal", "Takeout", "Google Photos", "Photos from 2023", "food_new.jpg")
        make_library.save(make_library.picture(999), new, make_library.ts("2024-05-05 12:00"))
        out = self.run_script("scan.py", self.lib, "--accounts").stdout
        self.assertIn("1 new", out)
        self.run_script("label_claude.py")
        calls = self.calls()[n_calls:]
        self.assertEqual(len(calls), 1)
        prompt = calls[0]["argv"][calls[0]["argv"].index("-p") + 1]
        self.assertEqual(len(re.findall(r"^\d+: ", prompt, re.M)), 1)   # only the new file was sent
        os.remove(new)
        self.run_script("scan.py", self.lib, "--accounts")
        self.before = snapshot(self.lib)

    def test_13_named_events_stay_inside(self):
        self.run_script("events.py", "--name")
        names = [e["name"] for e in self.data("events.json")]
        self.assertTrue(all("/" not in n and not n.startswith(".") for n in names), names)
        self.run_script("apply.py", self.out)
        for d in os.listdir(os.path.join(self.out, "Albums")):
            self.assertTrue(os.path.isdir(os.path.join(self.out, "Albums", d)))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "Escaped")))

    def test_14_highlights(self):
        out = self.run_script("highlights.py").stdout
        self.assertIn("2023", out)
        hl = self.data("highlights.json")
        self.assertTrue(hl["years"])
        for f in hl["files"]:
            self.assertTrue(f.startswith(os.path.join(self.out, "Highlights")))
        if shutil.which("ffprobe"):
            mp4 = next(f for f in hl["files"] if f.endswith(".mp4"))
            tags = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", mp4],
                                  capture_output=True, text=True).stdout
            self.assertNotIn("location", tags.lower())
        self.run_script("highlights.py", "--local")       # again: replaces, doesn't pile up
        self.assertEqual(len(glob.glob(os.path.join(self.out, "Highlights", "*.mp4"))), len([y for y in hl["years"].values() if y["video"]]))

    def test_15_trash_needs_matching_confirm(self):
        info = json.loads(self.run_script("trash_dupes.py", "--list").stdout)
        self.assertEqual(info["exact"], 1)
        self.assertEqual(self.run_script("trash_dupes.py", "--confirm", 5, ok=False).returncode, 1)
        inv = {r["id"]: r for r in self.data("inventory.json")}
        g = next(g for g in self.data("dupes.json") if g["type"] == "exact")
        keep, gone = inv[g["keep"]]["path"], inv[g["dupes"][0]]["path"]
        self.run_script("trash_dupes.py", "--confirm", 1)
        self.assertTrue(os.path.exists(keep))
        self.assertFalse(os.path.exists(gone))
        self.assertEqual(len(os.listdir(self.env["SNAPSIFT_TRASH_DIR"])), 1)
        # a duplicate that changed since the scan is skipped, never trashed
        near = next(g for g in self.data("dupes.json") if g["type"] == "near")
        p = inv[near["dupes"][0]]["path"]
        with open(p, "ab") as f:
            f.write(b"changed")
        n = json.loads(self.run_script("trash_dupes.py", "--list", "--near").stdout)["files"]
        out = self.run_script("trash_dupes.py", "--confirm", n, "--near").stdout
        self.assertIn("changed since the scan", out)
        self.assertTrue(os.path.exists(p))

    # ---------- rebuild safety ----------

    def out_files(self):
        out = {}
        for p in glob.glob(os.path.join(self.out, "**", "*"), recursive=True):
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    out[os.path.relpath(p, self.out)] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_16_rebuild_uses_the_chosen_folder(self):
        self.run_script("apply.py")  # like the dashboard's rebuild: no folder given
        self.assertFalse(os.path.exists(self.lib + " (sorted)"))
        self.assertTrue(os.path.exists(os.path.join(self.out, "sorted.csv")))

    def test_17_missing_photos_folder_changes_nothing(self):
        before = self.out_files()
        moved = self.lib + "-unplugged"
        os.rename(self.lib, moved)
        try:
            r = self.run_script("apply.py", ok=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("isn't there", r.stderr + r.stdout)
            self.assertEqual(self.out_files(), before)
        finally:
            os.rename(moved, self.lib)

    def test_18_copies_of_deleted_originals_are_kept(self):
        inv = {r["name"]: r for r in self.data("inventory.json")}
        orig = inv["party_03.jpg"]["path"]
        copies = [k for k in self.out_files() if k.endswith("party_03.jpg")]
        self.assertTrue(copies)
        os.rename(orig, orig + ".away")
        try:
            out = self.run_script("apply.py").stdout
            self.assertIn("kept", out)
            now = self.out_files()
            for c in copies:
                self.assertIn(c, now)          # the copy may be the only one left: it stays
            self.run_script("apply.py")        # and stays on the next rebuild too
            for c in copies:
                self.assertIn(c, self.out_files())
        finally:
            os.rename(orig + ".away", orig)

    def test_19_never_overwrites_or_deletes_your_files(self):
        sel = next(k for k in self.out_files() if k.endswith("selfie_02.jpg") and not k.startswith("Albums"))
        p = os.path.join(self.out, sel)
        with open(p, "ab") as f:
            f.write(b"my edit")                # you edited a sorted copy
        with open(p, "rb") as f:
            mine = f.read()
        self.run_script("apply.py")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), mine)   # left exactly as you made it
        self.assertTrue(any(k.startswith(os.path.dirname(sel)) and "selfie_02__" in k for k in self.out_files()))

    def test_20_unsafe_output_folders_are_refused(self):
        busy = os.path.join(self.tmp, "Documents")
        os.makedirs(busy)
        with open(os.path.join(busy, "taxes.pdf"), "w") as f:
            f.write("x")
        for dest in (busy, self.tmp, os.path.join(self.lib, "inside")):
            r = self.run_script("apply.py", dest, ok=False)
            self.assertNotEqual(r.returncode, 0, dest)
        self.assertEqual(os.listdir(busy), ["taxes.pdf"])

    def test_21_fake_video_playlist_is_not_followed(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("no ffmpeg")
        secret = os.path.join(self.tmp, "secret.txt")
        with open(secret, "w") as f:
            f.write("TOP SECRET")
        evil = os.path.join(self.lib, "personal", "evil.mp4")
        with open(evil, "w") as f:
            f.write(f"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10.0,\nfile://{secret}\n#EXT-X-ENDLIST\n")
        try:
            self.run_script("scan.py", self.lib, "--accounts")
            rec = next(r for r in self.data("inventory.json") if r["name"] == "evil.mp4")
            self.assertFalse(rec.get("duration"))      # ffmpeg refused to open it as a playlist
        finally:
            os.remove(evil)
            self.run_script("scan.py", self.lib, "--accounts")

    def test_22_your_folders_stay_out_of_git(self):
        self.assertTrue(os.path.exists(os.path.join(self.home, "config", "categories.json")))
        with open(os.path.join(ROOT, ".gitignore")) as f:
            self.assertIn("config/", f.read())


if __name__ == "__main__":
    unittest.main()
