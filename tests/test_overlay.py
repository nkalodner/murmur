"""Recording pill: anti-aliased image render, premultiplied BGRA packing, the
Tk-canvas fallback path, and Win32 struct layout."""
import ctypes
import sys
from ctypes import wintypes

import numpy as np
import pytest

from murmur import overlay as ov

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def test_supported_is_everything_but_macos():
    assert ov.supported() == (sys.platform != "darwin")


def test_render_rgba_is_antialiased_pill():
    img = ov.render_rgba("recording", [0.5] * ov.BARS)
    assert img.size == (ov.WIDTH, ov.HEIGHT) and img.mode == "RGBA"
    a = np.asarray(img)
    assert a[0, 0, 3] == 0, "corner is transparent"
    assert a[ov.HEIGHT // 2, ov.WIDTH // 2, 3] == 255, "center is opaque"
    mid_alphas = [int(a[ov.HEIGHT // 2, x, 3]) for x in range(ov.WIDTH)]
    assert any(0 < v < 255 for v in mid_alphas), "expected soft (anti-aliased) edge pixels"


def test_premultiplied_bgra():
    px = Image.new("RGBA", (1, 1), (200, 100, 50, 128))
    assert ov.premultiplied_bgra(px) == bytes([50 * 128 // 255, 100 * 128 // 255, 200 * 128 // 255, 128])
    assert len(ov.premultiplied_bgra(ov.render_rgba("recording", [0.3] * ov.BARS))) == ov.WIDTH * ov.HEIGHT * 4


class _FakeCanvas:
    def __init__(self):
        self.items = []

    def delete(self, *a):
        self.items = []

    def create_polygon(self, pts, **k):
        self.items.append(("poly", list(pts)))

    def create_rectangle(self, *a, **k):
        self.items.append(("rect", a))

    def create_oval(self, *a, **k):
        self.items.append(("oval", a))


def test_canvas_fallback_draws_capsule_and_bars_no_dot():
    p = ov.Pill(lambda: 0.7)
    p._layered = False
    p._canvas = _FakeCanvas()
    p._mode = "recording"
    for _ in range(40):
        p._draw_canvas()
    kinds = [it[0] for it in p._canvas.items]
    assert kinds.count("poly") == 1
    assert kinds.count("rect") == ov.BARS
    assert "oval" not in kinds  # the red dot is gone
    poly_pts = next(it[1] for it in p._canvas.items if it[0] == "poly")
    assert len(poly_pts) >= 6 and len(poly_pts) % 2 == 0


def test_win32_struct_layout():
    # BLENDFUNCTION is four bytes on every platform; the others use standard
    # wintypes so their layout is correct on Windows (where LONG/DWORD are 4B).
    assert ctypes.sizeof(ov._BLEND) == 4
    assert [t for _, t in ov._POINT._fields_] == [wintypes.LONG, wintypes.LONG]
    bmih_types = [t for _, t in ov._BMIH._fields_]
    assert bmih_types.count(wintypes.DWORD) == 5 and bmih_types.count(wintypes.LONG) == 4
