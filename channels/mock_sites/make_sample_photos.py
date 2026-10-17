"""Write small synthetic PNG "room photos" (flat color blocks, no real images) for mock uploads.

python -m channels.mock_sites.make_sample_photos
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).parent / "static" / "sample_photos"
COLORS = {"room-1-bed.png": (196, 170, 140), "room-2-window.png": (150, 180, 200), "room-3-bath.png": (220, 220, 225)}


def png(w: int, h: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = []
    for y in range(h):
        shade = 1 - 0.3 * y / h  # vertical gradient so it isn't a flat square
        px = bytes(int(c * shade) for c in rgb) * w
        rows.append(b"\x00" + px)
    raw = zlib.compress(b"".join(rows), 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def main() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rgb in COLORS.items():
        p = OUT / name
        p.write_bytes(png(320, 240, rgb))
        paths.append(p)
    return paths


if __name__ == "__main__":
    for p in main():
        print(p)
