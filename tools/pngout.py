"""Minimal PNG writer + line rasterizer (no third-party deps).

Used only by the site builder to emit geometry previews that a human can look
at; the web app draws the same geometry with canvas paths instead.
"""

from __future__ import annotations

import struct
import zlib


class Canvas:
    def __init__(self, w, h, bg=(15, 23, 42)):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(bg) * (w * h))

    def _put(self, x, y, c, a=1.0):
        x, y = int(round(x)), int(round(y))
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = (y * self.w + x) * 3
        if a >= 0.999:
            self.buf[i:i + 3] = bytes(c)
            return
        for k in range(3):
            self.buf[i + k] = int(self.buf[i + k] * (1 - a) + c[k] * a)

    def line(self, p0, p1, c=(229, 237, 247), width=1, a=1.0):
        x0, y0 = p0
        x1, y1 = p1
        span = max(abs(x1 - x0), abs(y1 - y0))
        n = max(1, int(span * 2.2))
        w = max(1, int(round(width)))
        for i in range(n + 1):
            t = i / n
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            if w == 1:
                self._put(x, y, c, a)
            else:
                r = (w - 1) / 2.0
                for dy in range(-int(r) - 1, int(r) + 2):
                    for dx in range(-int(r) - 1, int(r) + 2):
                        if dx * dx + dy * dy <= r * r + 0.6:
                            self._put(x + dx, y + dy, c, a)

    def dot(self, p, c=(239, 68, 68), r=3):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    self._put(p[0] + dx, p[1] + dy, c)

    def write(self, path):
        raw = b"".join(b"\x00" + bytes(self.buf[y * self.w * 3:(y + 1) * self.w * 3])
                       for y in range(self.h))

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data +
                    struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw, 6))
               + chunk(b"IEND", b""))
        with open(path, "wb") as fh:
            fh.write(png)
        return len(png)
