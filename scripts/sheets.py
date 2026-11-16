"""Contact sheets for Claude to look at.  python scripts/sheets.py [--sample]

Default: every file, 30 per sheet, each tagged with its id -> work/sheets/sheet_NN.jpg
--sample: 3 sheets of random files -> work/sample/, used to suggest folders that fit the library.
Videos are tagged "VIDEO 12s", PNGs "PNG" (usually screenshots).

make_sheets(..., big=True) makes 6 large tiles per sheet from the original photo (whole frame,
not cropped), for a closer second look at the photos Claude wasn't sure about.
"""
import os, random, shutil, sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))
from common import DATA, THUMBS, WORK, load

_font = {}


def font(size):
    if size not in _font:
        for f in ("/System/Library/Fonts/Helvetica.ttc", "arial.ttf", "DejaVuSans.ttf"):
            try:
                _font[size] = ImageFont.truetype(f, size)
                break
            except OSError:
                pass
        else:
            _font[size] = ImageFont.load_default()
    return _font[size]


def tile_image(r, size, big):
    if big and r["kind"] == "photo" and "error" not in r:
        try:
            with Image.open(r["path"]) as im:
                im.draft("RGB", (size * 2, size * 2))
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((size, size))
                canvas = Image.new("RGB", (size, size), (24, 24, 28))
                canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
                return canvas
        except Exception:
            pass
    with Image.open(os.path.join(THUMBS, f"{r['id']}.jpg")) as t:
        return t.convert("RGB").resize((size, size))


def make_sheets(recs, out, big=False, prefix="sheet"):
    """Returns [(sheet_path, [ids on it])]."""
    os.makedirs(out, exist_ok=True)
    cols, rows, C = (3, 2, 440) if big else (6, 5, 230)
    N = cols * rows
    f = font(26 if big else 22)
    made = []
    for s in range(0, len(recs), N):
        chunk = recs[s:s + N]
        im = Image.new("RGB", (cols * C, rows * C), "white")
        d = ImageDraw.Draw(im)
        for k, r in enumerate(chunk):
            x, y = (k % cols) * C, (k // cols) * C
            im.paste(tile_image(r, C - 8, big), (x + 4, y + 4))
            tag = str(r["id"])
            if r["kind"] == "video":
                tag += f" VIDEO {r.get('duration', 0) or 0:.0f}s"
            elif r["ext"] == ".png":
                tag += " PNG"
            d.rectangle((x + 4, y + 4, x + 14 + int(f.getlength(tag)) + 4, y + 36), fill="black")
            d.text((x + 9, y + 6), tag, fill="yellow", font=f)
        path = os.path.join(out, f"{prefix}_{s // N:03d}.jpg")
        im.save(path, quality=82)
        made.append((path, [r["id"] for r in chunk]))
    return made


if __name__ == "__main__":
    sample = "--sample" in sys.argv
    recs = load(os.path.join(DATA, "inventory.json"))
    out = os.path.join(WORK, "sample" if sample else "sheets")
    shutil.rmtree(out, ignore_errors=True)
    if sample:
        recs = random.Random(1).sample(recs, min(90, len(recs)))
    made = make_sheets(recs, out)
    print(f"{len(made)} sheets in {out}")
