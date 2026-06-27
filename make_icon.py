#!/usr/bin/env python3
"""Generate icon.png — a stylised FT8 "waterfall" — with the standard library only.

512×512 PNG: a dark navy field with a few bright cyan/green horizontal traces
(decoded signals) drifting across it. No third-party imaging dependency.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 512


def _png(pixels: bytes, width: int, height: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # filter type 0
        raw.extend(pixels[y * stride : (y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _render() -> bytes:
    buf = bytearray(SIZE * SIZE * 3)
    # background: deep navy with a subtle vertical gradient
    for y in range(SIZE):
        t = y / SIZE
        bg = (6, 10 + int(18 * t), 30 + int(40 * t))
        for x in range(SIZE):
            i = (y * SIZE + x) * 3
            buf[i] = bg[0]
            buf[i + 1] = bg[1]
            buf[i + 2] = bg[2]

    # bright traces — a handful of drifting horizontal signals
    traces = [
        (90, 0.018, (60, 255, 200)),
        (180, -0.010, (120, 220, 255)),
        (270, 0.026, (180, 255, 120)),
        (350, -0.020, (90, 230, 255)),
        (430, 0.012, (60, 255, 200)),
    ]
    for y0, drift, color in traces:
        for x in range(SIZE):
            yc = int(y0 + drift * (x - SIZE / 2) + 6 * math.sin(x / 28.0))
            for dy in range(-2, 3):
                y = yc + dy
                if 0 <= y < SIZE:
                    falloff = max(0.0, 1.0 - abs(dy) / 3.0)
                    i = (y * SIZE + x) * 3
                    for k in range(3):
                        buf[i + k] = min(255, int(buf[i + k] * (1 - falloff) + color[k] * falloff))
    return bytes(buf)


def main() -> None:
    out = Path(__file__).parent / "icon.png"
    out.write_bytes(_png(_render(), SIZE, SIZE))
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
