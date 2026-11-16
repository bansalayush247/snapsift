"""Builds a fake two-account Google Takeout library for the tests. Every image is drawn, none is a real photo.

  python tests/make_library.py /tmp/lib
"""
import json, os, random, shutil, subprocess, sys, time

import piexif
from PIL import Image, ImageDraw, ImageFilter

HOME_GPS = (28.6139, 77.2090)     # New Delhi
AWAY_GPS = (15.2993, 74.1240)     # Goa, ~1500 km away
TRICKY = 'x"; rm -rf ~ $(whoami) <img src=x onerror=alert(1)>.jpg'


def picture(seed, size=(640, 480)):
    rnd = random.Random(seed)
    im = Image.new("RGB", size, tuple(rnd.randint(0, 255) for _ in range(3)))
    d = ImageDraw.Draw(im)
    for _ in range(14):
        x, y = rnd.randint(0, size[0]), rnd.randint(0, size[1])
        r = rnd.randint(20, 160)
        box = (x, y, x + r, y + r)
        color = tuple(rnd.randint(0, 255) for _ in range(3))
        (d.ellipse if rnd.random() < .5 else d.rectangle)(box, fill=color)
    for _ in range(40):
        d.line([rnd.randint(0, size[0]), rnd.randint(0, size[1]), rnd.randint(0, size[0]), rnd.randint(0, size[1])],
               fill=(0, 0, 0), width=2)
    return im


def to_dms(v):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60 * 100)
    return ((d, 1), (m, 1), (s, 100))


def exif(when=None, gps=None, model=None, lens=None):
    ex = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    if when:
        ex["Exif"][piexif.ExifIFD.DateTimeOriginal] = time.strftime("%Y:%m:%d %H:%M:%S", time.localtime(when)).encode()
    if model:
        ex["0th"][piexif.ImageIFD.Make] = b"Apple"
        ex["0th"][piexif.ImageIFD.Model] = model.encode()
    if lens:
        ex["Exif"][piexif.ExifIFD.LensModel] = lens.encode()
    if gps:
        ex["GPS"] = {piexif.GPSIFD.GPSLatitudeRef: b"N" if gps[0] >= 0 else b"S", piexif.GPSIFD.GPSLatitude: to_dms(gps[0]),
                     piexif.GPSIFD.GPSLongitudeRef: b"E" if gps[1] >= 0 else b"W", piexif.GPSIFD.GPSLongitude: to_dms(gps[1])}
    return piexif.dump(ex)


def ts(s):
    return int(time.mktime(time.strptime(s, "%Y-%m-%d %H:%M")))


def save(im, path, when=None, gps=None, sidecar=None, model="iPhone 13", lens=None, raw=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path.endswith(".png"):
        im.save(path)
    elif raw:
        im.save(path, quality=90)
    else:
        im.save(path, quality=90, exif=exif(when, gps, model, lens))
    if sidecar:
        j = {"title": os.path.basename(path), "photoTakenTime": {"timestamp": str(sidecar[0])}}
        if sidecar[1]:
            j["geoData"] = {"latitude": sidecar[1][0], "longitude": sidecar[1][1], "altitude": 0}
        with open(path + ".supplemental-metadata.json", "w") as f:
            json.dump(j, f)


def build(root):
    shutil.rmtree(root, ignore_errors=True)
    p = os.path.join(root, "personal", "Takeout", "Google Photos", "Photos from 2023")
    w = os.path.join(root, "work", "Takeout", "Google Photos", "Photos from 2023")
    seed = 0

    def nxt():
        nonlocal seed
        seed += 1
        return seed

    food = picture(nxt())
    save(food, os.path.join(p, "food_1.jpg"), ts("2023-06-01 13:00"), HOME_GPS)
    os.makedirs(w, exist_ok=True)
    shutil.copy(os.path.join(p, "food_1.jpg"), os.path.join(w, "food_1.jpg"))     # identical copy in the other account

    for i in range(12):                                                          # a trip: far from home, 5 days
        save(picture(nxt()), os.path.join(p, f"beach_trip_{i:02d}.jpg"), ts(f"2023-12-{10 + i // 3} {9 + i % 3 * 3}:00"),
             (AWAY_GPS[0] + i * 0.01, AWAY_GPS[1]), sidecar=(ts(f"2023-12-{10 + i // 3} {9 + i % 3 * 3}:00"), (AWAY_GPS[0] + i * 0.01, AWAY_GPS[1])))
    big = Image.open(os.path.join(p, "beach_trip_03.jpg"))
    save(big.resize((320, 240)), os.path.join(w, "beach_trip_03_small.jpg"), ts("2023-12-11 12:00"))  # storage-saver copy

    for i in range(9):                                                           # an event at home
        save(picture(nxt()), os.path.join(p, f"party_{i:02d}.jpg"), ts("2024-03-02 19:00") + i * 900, HOME_GPS)

    for i in range(6):                                                           # everyday photos, other days
        save(picture(nxt()), os.path.join(p, f"selfie_{i:02d}.jpg"), ts(f"2024-0{i + 1}-15 10:00"), HOME_GPS, lens="iPhone 13 front camera")

    save(picture(nxt()), os.path.join(p, "passport.jpg"), ts("2023-02-01 10:00"))
    save(picture(nxt()).filter(ImageFilter.GaussianBlur(25)), os.path.join(p, "blurry.jpg"), ts("2023-02-02 10:00"))
    save(Image.new("RGB", (640, 480), (3, 3, 4)), os.path.join(p, "dark.jpg"), ts("2023-02-03 10:00"))
    save(picture(nxt()), os.path.join(p, "mystery.jpg"), ts("2023-02-04 10:00"))

    orig = picture(nxt())
    save(orig, os.path.join(p, "IMG_100.jpg"), ts("2023-03-01 10:00"))
    save(orig.point(lambda v: min(255, v + 25)), os.path.join(p, "IMG_100-edited.jpg"), ts("2023-03-01 10:00"))

    shot = Image.new("RGB", (390, 844), (250, 250, 250))
    d = ImageDraw.Draw(shot)
    for i in range(20):
        d.rectangle((20, 20 + i * 40, 370, 50 + i * 40), fill=(30 + i * 9, 120, 200))
    save(shot, os.path.join(p, "screenshot_a.png"))

    # a WhatsApp-style photo: no EXIF at all, date only in the Takeout sidecar
    save(picture(nxt()), os.path.join(p, "whatsapp_img.jpg"), raw=True, sidecar=(ts("2022-08-15 18:30"), None))

    burst = picture(nxt())
    save(burst, os.path.join(w, "burst_a.jpg"), ts("2023-07-01 10:00"))
    save(burst.filter(ImageFilter.GaussianBlur(1.6)), os.path.join(w, "burst_b.jpg"), ts("2023-07-01 10:00"))

    save(picture(nxt()), os.path.join(w, TRICKY), ts("2023-04-01 10:00"))

    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
                        "-pix_fmt", "yuv420p", os.path.join(p, "clip.mp4")], check=True)
    return root


if __name__ == "__main__":
    print(build(sys.argv[1]))
