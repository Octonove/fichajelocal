"""Genera build/icon.ico para FichajeLocal (reloj de fichar + check)."""

from pathlib import Path
from PIL import Image, ImageDraw

NAVY = (30, 58, 95, 255)
NAVY2 = (21, 48, 77, 255)
TERRA = (206, 110, 97, 255)
GREEN = (22, 163, 74, 255)
WHITE = (255, 255, 255, 255)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=NAVY)
    d.rounded_rectangle([0, int(size * 0.5), size - 1, size - 1], radius=r, fill=NAVY2)
    # esfera del reloj de fichar
    cx, cy = int(size * 0.5), int(size * 0.48)
    rad = int(size * 0.30)
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=WHITE)
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=TERRA,
              width=max(2, size // 24))
    # agujas (8 en punto: hora de fichar)
    d.line([cx, cy, cx, int(cy - rad * 0.62)], fill=NAVY, width=max(2, size // 26))
    d.line([cx, cy, int(cx - rad * 0.45), int(cy + rad * 0.32)], fill=NAVY,
           width=max(2, size // 26))
    d.ellipse([cx - size // 28, cy - size // 28, cx + size // 28, cy + size // 28], fill=TERRA)
    # check de fichaje correcto
    ck = int(size * 0.17)
    ox, oy = int(size * 0.64), int(size * 0.66)
    d.line([ox, oy + ck // 2, ox + ck // 2, oy + ck], fill=GREEN, width=max(3, size // 15))
    d.line([ox + ck // 2, oy + ck, ox + ck + ck // 3, oy - ck // 4], fill=GREEN,
           width=max(3, size // 15))
    return img


def main() -> None:
    out = Path(__file__).resolve().parent / "icon.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [make(s) for s in sizes]
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
    make(256).save(out.with_name("icon_preview.png"))
    print("icono ->", out)


if __name__ == "__main__":
    main()
