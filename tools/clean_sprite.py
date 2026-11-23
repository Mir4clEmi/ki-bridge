"""Sprite säubern: Alpha hart schwellen (entfernt Glow), zuschneiden, pixelgenau verkleinern.
Nutzung: python tools/clean_sprite.py eingabe.png ausgabe.png [hoehe_px] [alpha_schwelle]"""
import sys
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
height = int(sys.argv[3]) if len(sys.argv) > 3 else 96
thr = int(sys.argv[4]) if len(sys.argv) > 4 else 200
im = Image.open(src).convert("RGBA")
a = im.getchannel("A").point(lambda v: 255 if v >= thr else 0)
im.putalpha(a)
im = im.crop(a.getbbox())
w = round(im.width * height / im.height)
im = im.resize((w, height), Image.NEAREST)
im.save(dst)
h = im.getchannel("A").histogram()
print(f"{dst}: {im.size}, deckend {100*h[255]/sum(h):.0f} %, transparent {100*h[0]/sum(h):.0f} %")
