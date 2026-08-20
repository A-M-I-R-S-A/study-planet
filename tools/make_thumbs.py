#!/usr/bin/env python3
"""Generate the swatch thumbnails for media/backgrounds/.

Why this exists
---------------
The background picker in the timer draws each option at about 70 pixels. It used to point
those swatches at the originals, which are full-resolution photographs of two to three
megabytes each -- so opening Settings once downloaded roughly 30MB to paint a grid of
thumbnails. `bg_payload()` in server.py now offers a `thumb` alongside each image, and the
picker uses it when there is one.

The server cannot make these itself: it is standard-library only by design (no Pillow on
cPanel shared hosting), and nothing in the standard library resizes a JPEG. New uploads are
therefore downscaled in the admin's browser at upload time, which covers everything added
from the panel. This script is for the images that were already there before that existed --
run it once against your media directory, then upload media/backgrounds/thumb/ with the rest.

Usage
-----
    python tools/make_thumbs.py                 # media/backgrounds next to the repo
    python tools/make_thumbs.py path/to/media/backgrounds
    python tools/make_thumbs.py --force         # rebuild thumbnails that already exist

Needs Pillow (`pip install Pillow`) on whatever machine you run it on -- your laptop is
fine, the server does not need it. Originals are never modified; this only adds files.
"""
import os
import sys

BOX = 320       # swatches render at ~70px; 320 covers 3x-density screens
QUALITY = 78
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def main(argv):
    force = "--force" in argv
    args = [a for a in argv if not a.startswith("-")]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = args[0] if args else os.path.join(root, "media", "backgrounds")
    if not os.path.isdir(src):
        print("No such directory: %s" % src)
        return 1
    try:
        from PIL import Image
    except ImportError:
        print("This script needs Pillow.  pip install Pillow")
        return 1

    dst = os.path.join(src, "thumb")
    os.makedirs(dst, exist_ok=True)
    made = skipped = failed = 0
    total_in = total_out = 0

    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if not os.path.isfile(path):
            continue                      # skips thumb/ and u/ (the students' own uploads)
        stem, ext = os.path.splitext(name)
        if ext.lower() not in EXTS:
            continue
        # Named after the original with a .jpg extension, which is what thumb_for() derives.
        out = os.path.join(dst, stem + ".jpg")
        if os.path.exists(out) and not force:
            skipped += 1
            continue
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((BOX, BOX), Image.LANCZOS)
                im.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        except Exception as exc:
            print("  ! %-30s %s" % (name, exc))
            failed += 1
            continue
        a, b = os.path.getsize(path), os.path.getsize(out)
        total_in += a
        total_out += b
        made += 1
        print("  %-30s %8.1f KB -> %6.1f KB" % (name, a / 1024.0, b / 1024.0))

    print("")
    print("made %d, skipped %d (already had one), failed %d" % (made, skipped, failed))
    if made:
        print("the swatch grid now costs %.2f MB instead of %.1f MB"
              % (total_out / 1048576.0, total_in / 1048576.0))
    print("upload %s along with the rest of media/" % os.path.relpath(dst, root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
