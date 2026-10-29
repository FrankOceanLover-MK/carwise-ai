"""Generate the chat avatar icons (original artwork, no third-party assets).

    python -m scripts.make_avatars
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "frontend" / "assets"
S, K = 128, 4  # final size, supersampling factor


def _canvas():
    img = Image.new("RGBA", (S * K, S * K), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _finish(img, name):
    OUT.mkdir(parents=True, exist_ok=True)
    img.resize((S, S), Image.LANCZOS).save(OUT / name)


def bot():
    img, d = _canvas()
    u = K
    d.rounded_rectangle([0, 0, S * u - 1, S * u - 1], radius=30 * u, fill="#4f46e5")
    white, ink = "#ffffff", "#4f46e5"
    d.rounded_rectangle([20 * u, 62 * u, 108 * u, 88 * u], radius=9 * u, fill=white)          # body
    d.polygon([(36 * u, 62 * u), (49 * u, 40 * u), (82 * u, 40 * u), (97 * u, 62 * u)], fill=white)  # cabin
    d.polygon([(46 * u, 60 * u), (54 * u, 45 * u), (65 * u, 45 * u), (65 * u, 60 * u)], fill=ink)    # window
    d.polygon([(70 * u, 60 * u), (70 * u, 45 * u), (80 * u, 45 * u), (90 * u, 60 * u)], fill=ink)    # window
    for cx in (40, 88):
        d.ellipse([(cx - 11) * u, 77 * u, (cx + 11) * u, 99 * u], fill=ink)
        d.ellipse([(cx - 8) * u, 80 * u, (cx + 8) * u, 96 * u], fill=white)
        d.ellipse([(cx - 3) * u, 85 * u, (cx + 3) * u, 91 * u], fill=ink)
    _finish(img, "carwise.png")


def user():
    img, d = _canvas()
    u = K
    d.rounded_rectangle([0, 0, S * u - 1, S * u - 1], radius=30 * u, fill="#334155")
    d.ellipse([46 * u, 28 * u, 82 * u, 64 * u], fill="#ffffff")                        # head
    d.pieslice([26 * u, 70 * u, 102 * u, 146 * u], 180, 360, fill="#ffffff")           # shoulders
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S * u - 1, S * u - 1], radius=30 * u, fill=255)
    img.putalpha(mask)                                                                  # clip shoulders to the tile
    _finish(img, "user.png")


if __name__ == "__main__":
    bot()
    user()
    print("wrote", OUT)
