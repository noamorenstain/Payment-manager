"""Generate the app icon (PNG + multi-size ICO) using only the standard library.

Design: blue rounded square with a white document showing three lines and a green check.
Run:  python scripts/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "img"

BLUE = (31, 95, 209)
WHITE = (255, 255, 255)
LINE = (170, 186, 214)
GREEN = (30, 125, 59)


def _rounded_rect(x, y, x0, y0, x1, y1, r):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _dist_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx, qy = ax + t * dx, ay + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


def _sample(u, v):
    """Colour (r, g, b, a) at normalised coordinates u, v in [0, 1]."""
    if not _rounded_rect(u, v, 0.02, 0.02, 0.98, 0.98, 0.2):
        return (0, 0, 0, 0)
    colour = BLUE
    if _rounded_rect(u, v, 0.24, 0.16, 0.76, 0.84, 0.06):
        colour = WHITE
        for ly in (0.32, 0.45, 0.58):
            if 0.33 <= u <= 0.67 and abs(v - ly) <= 0.025:
                colour = LINE
    # Check mark badge (bottom-left in image space)
    if (u - 0.70) ** 2 + (v - 0.72) ** 2 <= 0.17 ** 2:
        colour = GREEN
        if (_dist_to_segment(u, v, 0.62, 0.72, 0.68, 0.78) <= 0.028
                or _dist_to_segment(u, v, 0.68, 0.78, 0.79, 0.65) <= 0.028):
            colour = WHITE
    return (*colour, 255)


def render(size: int, ss: int = 4) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])  # PNG filter type 0
        for x in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    r, g, b, a = _sample((x + (sx + 0.5) / ss) / size, (y + (sy + 0.5) / ss) / size)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            n = ss * ss
            alpha = acc[3] / n
            if acc[3]:
                row += bytes((round(acc[0] / acc[3]), round(acc[1] / acc[3]), round(acc[2] / acc[3]), round(alpha)))
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))
    return _png(size, size, b"".join(rows))


def _png(w: int, h: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(pngs: dict[int, bytes]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(pngs)
    for size, data in sorted(pngs.items()):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pngs = {s: render(s) for s in (16, 32, 48, 256)}
    (OUT_DIR / "icon.png").write_bytes(render(64))
    (OUT_DIR / "icon.ico").write_bytes(ico(pngs))
    print(f"Wrote {OUT_DIR / 'icon.png'} and {OUT_DIR / 'icon.ico'}")


if __name__ == "__main__":
    main()
