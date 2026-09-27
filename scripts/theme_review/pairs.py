"""Side-by-side planches: reference captures (left) vs new captures (right).

Usage: python scripts/theme_review/pairs.py <ref_dir> <new_dir> <out_dir> [--only=<theme>]...
  <ref_dir> and <new_dir> are output dirs of capture.py (they hold <theme>/).
Writes <out_dir>/<theme>/<mode>__<view>.png and prints, per planche, the share
of pixels that changed (a quick way to find the views worth opening first).
Needs Pillow.
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 3:
        print(__doc__)
        return 2
    ref_dir, new_dir, out_dir = (Path(a) for a in args)
    only = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")]
    themes = sorted(p.name for p in ref_dir.iterdir() if p.is_dir() and (not only or p.name in only))
    for theme in themes:
        (out_dir / theme).mkdir(parents=True, exist_ok=True)
        for bpath in sorted((ref_dir / theme).glob("*.png")):
            apath = new_dir / theme / bpath.name
            if not apath.exists():
                print(f"{theme}/{bpath.stem}: missing in {new_dir}")
                continue
            b, a = Image.open(bpath).convert("RGB"), Image.open(apath).convert("RGB")
            diff = ImageChops.difference(b, a.resize(b.size)).convert("L").point(lambda v: 255 if v > 24 else 0)
            changed = round(100 * diff.histogram()[255] / (b.width * b.height), 1)
            canvas = Image.new("RGB", (b.width + a.width + 12, max(b.height, a.height) + 28), (40, 40, 40))
            canvas.paste(b, (0, 28))
            canvas.paste(a, (b.width + 12, 28))
            draw = ImageDraw.Draw(canvas)
            draw.text((8, 6), f"REFERENCE  {theme} {bpath.stem}", fill=(255, 210, 120))
            draw.text((b.width + 20, 6), f"NEW  ({changed}% of pixels changed)", fill=(140, 230, 160))
            canvas.save(out_dir / theme / bpath.name)
            print(f"{theme}/{bpath.stem}: {changed}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
