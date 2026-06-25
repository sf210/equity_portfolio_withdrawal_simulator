#!/usr/bin/env python3
"""Generate the app icon (PNG/ICO/ICNS) for the Monte Carlo simulator.

Draws a rounded-square badge with a Monte Carlo "fan" of equity paths over a
zero baseline, evoking the simulation's diverging-outcome charts. Deterministic
(fixed seed) so re-running produces the same art.
"""
import math
import os
import random

from PIL import Image, ImageDraw

OUT = os.path.dirname(os.path.abspath(__file__))
SIZE = 1024
SS = 4                      # supersample factor for smooth curves
W = SIZE * SS


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size), top)
    px = img.load()
    for y in range(size):
        c = lerp(top, bottom, y / (size - 1))
        for x in range(size):
            px[x, y] = c
    return img


def build():
    top = (16, 52, 96)         # deep blue
    bottom = (10, 122, 122)    # teal
    base = vertical_gradient(W, top, bottom)
    draw = ImageDraw.Draw(base, "RGBA")

    # Plot area inside the badge.
    pad = W * 0.16
    x0, x1 = pad, W - pad
    y0, y1 = W * 0.20, W - pad           # y0 top, y1 bottom
    baseline = (y0 + y1) / 2             # "starting balance" line

    # Faint baseline.
    draw.line([(x0, baseline), (x1, baseline)],
              fill=(255, 255, 255, 90), width=SS * 3)

    rnd = random.Random(7)
    n_paths = 18
    steps = 60
    span = (y1 - y0) * 0.40

    for i in range(n_paths):
        drift = (i / (n_paths - 1) - 0.5) * 1.5   # spread of final outcomes
        y = baseline
        pts = [(x0, y)]
        vol = span * 0.045
        for s in range(1, steps + 1):
            t = s / steps
            y += rnd.gauss(drift * span / steps * 0.9, vol)
            x = x0 + (x1 - x0) * t
            yy = max(y0, min(y1, y))
            pts.append((x, yy))
        # Outer paths fainter; tint by up/down outcome.
        if pts[-1][1] < baseline:
            col = (180, 245, 215)      # gains: light green
        else:
            col = (255, 196, 170)      # losses: warm
        alpha = 130
        draw.line(pts, fill=col + (alpha,), width=SS * 3, joint="curve")

    # Median path, bold white.
    y = baseline
    pts = [(x0, y)]
    for s in range(1, steps + 1):
        t = s / steps
        y += rnd.gauss(-span / steps * 0.15, span * 0.012)
        pts.append((x0 + (x1 - x0) * t, y))
    draw.line(pts, fill=(255, 255, 255, 255), width=SS * 6, joint="curve")

    # Downscale and round the corners.
    icon = base.resize((SIZE, SIZE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(icon, (0, 0), rounded_mask(SIZE, int(SIZE * 0.22)))
    return out


def main():
    icon = build()
    png = os.path.join(OUT, "icon.png")
    icon.save(png)
    # Linux menu commonly wants a 256px too; the 1024 scales fine via the .desktop.
    sizes = [16, 24, 32, 48, 64, 128, 256]
    icon.save(os.path.join(OUT, "icon.ico"),
              sizes=[(s, s) for s in sizes])
    # ICNS requires square power-of-two; PIL handles the resampling.
    icon.convert("RGBA").save(os.path.join(OUT, "icon.icns"))
    print("wrote icon.png, icon.ico, icon.icns to", OUT)


if __name__ == "__main__":
    main()
