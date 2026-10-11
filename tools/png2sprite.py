#!/usr/bin/env python3
"""Turn a small image into a 1-bit sprite the firmware can draw.

Written because hand-plotting a convincing dragon from primitives did not work
-- three attempts, all abandoned. Drop in any small picture instead and this
emits a byte array for TFT_eSPI's drawBitmap, which costs ~200 bytes of flash
and needs no SD card.

    python tools/png2sprite.py dragon.png --width 48 --name DRAGON > sprite.h

Any single-colour silhouette works best: it is thresholded to one bit, so
detail and shading are lost by design. Requires Pillow (uv run --with pillow).
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--width", type=int, default=48, help="resize to this width")
    ap.add_argument("--name", default="SPRITE")
    ap.add_argument("--threshold", type=int, default=128,
                    help="pixels darker than this become ink")
    ap.add_argument("--invert", action="store_true",
                    help="use for a light subject on a dark background")
    a = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("needs Pillow:  uv run --with pillow python tools/png2sprite.py ...",
              file=sys.stderr)
        return 1

    im = Image.open(a.image).convert("L")
    h = max(1, round(im.height * a.width / im.width))
    im = im.resize((a.width, h), Image.LANCZOS)

    rows = []
    for y in range(h):
        bits = []
        for x in range(a.width):
            v = im.getpixel((x, y))
            ink = v < a.threshold
            bits.append(not ink if a.invert else ink)
        rows.append(bits)

    stride = (a.width + 7) // 8
    out = []
    for bits in rows:
        for byte_i in range(stride):
            b = 0
            for bit in range(8):
                x = byte_i * 8 + bit
                if x < a.width and bits[x]:
                    b |= 0x80 >> bit
            out.append(b)

    print(f"// {a.image}, {a.width}x{h}, {len(out)} bytes")
    print(f"#define {a.name}_W {a.width}")
    print(f"#define {a.name}_H {h}")
    print(f"static const uint8_t {a.name}[] PROGMEM = {{")
    for i in range(0, len(out), 12):
        print("  " + ", ".join(f"0x{v:02X}" for v in out[i:i + 12]) + ",")
    print("};")
    print()
    print("// Draw it (scale 1):  tft.drawBitmap(x, y, %s, %s_W, %s_H, colour);"
          % (a.name, a.name, a.name))
    # A preview, so you can see what you are about to compile in.
    print()
    print("/* preview")
    for bits in rows:
        print("".join("#" if b else " " for b in bits).rstrip())
    print("*/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
