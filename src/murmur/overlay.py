"""The recording pill: a small always-on-top overlay that shows Murmur is
listening, with live bars that dance to the mic level.

Two rendering paths, same animation:

- Windows: a per-pixel-alpha layered window (`UpdateLayeredWindow`). The pill
  is drawn as an anti-aliased image with PIL and pushed to the window, so the
  rounded corners are genuinely smooth against whatever is behind them. Tk's
  own canvas has no anti-aliasing, so its curves stair-step; this avoids that.
- Linux (and Windows if the layered setup fails): the Tk canvas, drawn as a
  single rounded-rect polygon. Aliased, but the fallback only really runs in
  headless test environments.

tkinter still owns the window lifecycle on both paths (creation, positioning,
topmost, the animation timer), running entirely on its own thread; the rest of
the app only posts commands to a queue the Tk thread drains.

Platform note: on macOS, Tcl/Tk must run on the process main thread, which
pystray's menu-bar loop already occupies, so the pill can't coexist with the
tray. The pill is therefore Windows + Linux only; macOS falls back to the tray
dot. `App` gates on that before constructing this.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from ctypes import wintypes
from typing import Callable

log = logging.getLogger("murmur")

WIDTH, HEIGHT = 46, 18  # compact pill; dot removed, bars only (0.5.6)
BARS = 7
KEY = "#08090b"  # Tk-canvas transparency key / background (fallback path only)
CAPSULE = (23, 25, 29)  # pill fill
BORDER = (43, 47, 54)  # pill outline
ACCENT = (56, 189, 248)  # recording bars (sky)
DIM = (91, 100, 112)  # transcribing shimmer bars


def _hex(c: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % c


def supported() -> bool:
    # Not macOS (main-thread Tk clash with pystray). Also needs a display.
    return sys.platform != "darwin"


# -- Win32 structs, defined unconditionally (they don't call any API, and
#    ctypes.wintypes exists on every platform, so sizes stay testable) --------


class _BMIH(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class _BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", _BMIH), ("bmiColors", wintypes.DWORD * 3)]


class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


def render_rgba(mode: str, bar_h, ss: int = 4):
    """The pill as an anti-aliased RGBA image (supersampled ss x, then
    downscaled). Pure and importable, so tests can inspect it."""
    from PIL import Image, ImageDraw

    w, h = WIDTH * ss, HEIGHT * ss
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = (h - 2 * ss) / 2  # fully rounded ends (stadium)
    d.rounded_rectangle([ss, ss, w - 1 - ss, h - 1 - ss], radius=r,
                        fill=CAPSULE + (255,), outline=BORDER + (255,), width=ss)
    color = (ACCENT if mode == "recording" else DIM) + (255,)
    mid = h / 2
    bw, gap = 3 * ss, 2 * ss
    span = BARS * bw + (BARS - 1) * gap
    bx0 = (w - span) / 2
    max_h = (HEIGHT - 8) * ss
    for i in range(BARS):
        bh = max(2 * ss, bar_h[i] * max_h)
        x = bx0 + i * (bw + gap)
        d.rectangle([x, mid - bh / 2, x + bw - 1, mid + bh / 2], fill=color)
    return img.resize((WIDTH, HEIGHT), Image.LANCZOS)


def premultiplied_bgra(img) -> bytes:
    """RGBA PIL image -> premultiplied BGRA bytes, the format a 32-bit
    top-down DIB wants for UpdateLayeredWindow."""
    import numpy as np

    a = np.asarray(img, dtype=np.uint16)  # H x W x 4, RGBA
    alpha = a[..., 3]
    out = np.empty((img.height, img.width, 4), dtype=np.uint8)
    out[..., 0] = a[..., 2] * alpha // 255  # B
    out[..., 1] = a[..., 1] * alpha // 255  # G
    out[..., 2] = a[..., 0] * alpha // 255  # R
    out[..., 3] = alpha
    return out.tobytes()


class Pill:
    def __init__(self, level_provider: Callable[[], float]):
        self._level = level_provider
        self._root = None
        self._canvas = None
        self._thread = None
        self._ready = threading.Event()
        self._cmds: queue.SimpleQueue = queue.SimpleQueue()
        self._mode = "hidden"  # hidden | recording | transcribing
        self._visible = False
        self._phase = 0.0
        self._bar_h = [0.0] * BARS
        self._layered = False
        self._need_clear = False
        self._x = self._y = 0
        self.ok = False

    # -- public API: post commands, never touch Tk from here -------------

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="murmur-pill", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self.ok

    def show(self, mode: str) -> None:
        self._cmds.put(("show", mode))

    def hide(self) -> None:
        self._cmds.put(("hide", None))

    def stop(self) -> None:
        self._cmds.put(("stop", None))
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)

    # -- Tk thread -------------------------------------------------------

    def _run(self) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            self._x = (sw - WIDTH) // 2
            self._y = max(0, sh - HEIGHT - 96)  # float above the taskbar
            root.geometry(f"{WIDTH}x{HEIGHT}+{self._x}+{self._y}")
            self._root = root
            root.update_idletasks()

            if sys.platform == "win32":
                try:
                    self._init_layered(root)
                    self._layered = True
                    root.deiconify()  # ULW needs the window shown; a clear frame keeps it invisible
                    self._clear_layered()
                except Exception as e:
                    log.debug("smooth (layered) pill unavailable (%s); using the canvas fallback", e)
                    self._layered = False

            if not self._layered:
                try:
                    root.attributes("-alpha", 0.97)
                except tk.TclError:
                    pass
                if sys.platform == "win32":
                    try:
                        root.attributes("-transparentcolor", KEY)
                    except tk.TclError:
                        pass
                root.configure(bg=KEY)
                self._canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg=KEY, highlightthickness=0)
                self._canvas.pack()
                if sys.platform == "win32":
                    self._make_noactivate(root)

            self.ok = True
            self._ready.set()
            self._loop()
            root.mainloop()
        except Exception as e:
            log.debug("recording pill unavailable: %s", e)
            self.ok = False
            self._ready.set()
        finally:
            self._teardown_layered()
            self._canvas = None
            self._root = None

    # -- Windows layered-window painting ---------------------------------

    def _init_layered(self, root) -> None:
        self._u32 = ctypes.windll.user32
        self._g32 = ctypes.windll.gdi32
        u32, g32 = self._u32, self._g32
        # Type every call: on 64-bit Windows these handles are pointer-sized,
        # and the ctypes default (c_int) would silently truncate them.
        u32.GetParent.restype = wintypes.HWND
        u32.GetParent.argtypes = [wintypes.HWND]
        u32.GetWindowLongW.restype = wintypes.LONG
        u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetWindowLongW.restype = wintypes.LONG
        u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        u32.GetDC.restype = wintypes.HDC
        u32.GetDC.argtypes = [wintypes.HWND]
        u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        g32.CreateCompatibleDC.restype = wintypes.HDC
        g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g32.CreateDIBSection.restype = wintypes.HBITMAP
        g32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BMI), wintypes.UINT,
                                         ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        g32.SelectObject.restype = wintypes.HGDIOBJ
        g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g32.DeleteDC.argtypes = [wintypes.HDC]
        u32.UpdateLayeredWindow.restype = wintypes.BOOL
        u32.UpdateLayeredWindow.argtypes = [
            wintypes.HWND, wintypes.HDC, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
            wintypes.HDC, ctypes.POINTER(_POINT), wintypes.DWORD, ctypes.POINTER(_BLEND), wintypes.DWORD]

        parent = u32.GetParent(wintypes.HWND(root.winfo_id()))
        self._hwnd = wintypes.HWND(parent if parent else root.winfo_id())
        GWL_EXSTYLE = -20
        WS_EX = 0x80000 | 0x20 | 0x8000000 | 0x80  # LAYERED | TRANSPARENT | NOACTIVATE | TOOLWINDOW
        style = u32.GetWindowLongW(self._hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        u32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, (style | WS_EX) & 0xFFFFFFFF)

        self._screen = u32.GetDC(None)
        self._memdc = g32.CreateCompatibleDC(self._screen)
        bmi = _BMI()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
        bmi.bmiHeader.biWidth = WIDTH
        bmi.bmiHeader.biHeight = -HEIGHT  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        self._bits = ctypes.c_void_p()
        self._hbmp = g32.CreateDIBSection(self._memdc, ctypes.byref(bmi), 0, ctypes.byref(self._bits), None, 0)
        if not self._hbmp:
            raise OSError("CreateDIBSection failed")
        self._oldbmp = g32.SelectObject(self._memdc, self._hbmp)
        self._blend = _BLEND(0, 0, 248, 1)  # AC_SRC_OVER, ~0.97 constant alpha, AC_SRC_ALPHA
        self._pos = _POINT(self._x, self._y)
        self._size = _SIZE(WIDTH, HEIGHT)
        self._src = _POINT(0, 0)
        self._nbytes = WIDTH * HEIGHT * 4

    def _push(self, buf: bytes) -> None:
        ctypes.memmove(self._bits, buf, self._nbytes)
        self._u32.UpdateLayeredWindow(
            self._hwnd, self._screen, ctypes.byref(self._pos), ctypes.byref(self._size),
            self._memdc, ctypes.byref(self._src), 0, ctypes.byref(self._blend), 2)  # ULW_ALPHA

    def _paint_layered(self) -> None:
        self._advance(self._mode == "recording")
        self._push(premultiplied_bgra(render_rgba(self._mode, self._bar_h)))

    def _clear_layered(self) -> None:
        self._push(b"\x00" * self._nbytes)  # fully transparent -> invisible

    def _teardown_layered(self) -> None:
        if not self._layered:
            return
        try:
            if getattr(self, "_oldbmp", None):
                self._g32.SelectObject(self._memdc, self._oldbmp)
            if getattr(self, "_hbmp", None):
                self._g32.DeleteObject(self._hbmp)
            if getattr(self, "_memdc", None):
                self._g32.DeleteDC(self._memdc)
            if getattr(self, "_screen", None):
                self._u32.ReleaseDC(None, self._screen)
        except Exception as e:
            log.debug("layered teardown: %s", e)

    # -- shared animation ------------------------------------------------

    def _advance(self, recording: bool) -> None:
        import math

        self._phase += 0.35
        level = max(0.05, min(1.0, self._level())) if recording else 0.0
        for i in range(BARS):
            if recording:
                target = level * (0.55 + 0.45 * math.sin(self._phase + i * 0.9))
            else:  # transcribing: a gentle traveling shimmer
                target = 0.25 + 0.22 * math.sin(self._phase * 0.6 + i * 0.7)
            self._bar_h[i] += (target - self._bar_h[i]) * 0.4

    # -- Tk canvas painting (Linux / fallback) ---------------------------

    def _make_noactivate(self, root) -> None:
        """Stop the overlay from stealing keyboard focus from the target app."""
        try:
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception as e:
            log.debug("pill no-activate failed: %s", e)

    def _capsule(self) -> None:
        """The pill outline as one filled polygon (single clean stroke, no
        seams). Aliased — Tk can't anti-alias — used only on the canvas path."""
        import math

        pad = 1
        x0, y0, x1, y1 = pad, pad, WIDTH - pad, HEIGHT - pad
        r = (y1 - y0) / 2
        steps = 8
        corners = (
            (x1 - r, y0 + r, -math.pi / 2), (x1 - r, y1 - r, 0.0),
            (x0 + r, y1 - r, math.pi / 2), (x0 + r, y0 + r, math.pi),
        )
        pts = []
        for cx, cy, start in corners:
            for s in range(steps + 1):
                a = start + (math.pi / 2) * (s / steps)
                pts.extend((cx + r * math.cos(a), cy + r * math.sin(a)))
        self._canvas.create_polygon(pts, fill=_hex(CAPSULE), outline=_hex(BORDER), width=1)

    def _draw_canvas(self) -> None:
        c = self._canvas
        c.delete("all")
        self._capsule()
        recording = self._mode == "recording"
        self._advance(recording)
        mid = HEIGHT / 2
        bw, gap = 3, 2
        span = BARS * bw + (BARS - 1) * gap
        bx0 = (WIDTH - span) / 2
        max_h = HEIGHT - 8
        color = _hex(ACCENT) if recording else _hex(DIM)
        for i in range(BARS):
            h = max(2.0, self._bar_h[i] * max_h)
            x = bx0 + i * (bw + gap)
            c.create_rectangle(x, mid - h / 2, x + bw, mid + h / 2, fill=color, outline="")

    # -- animation loop (Tk thread) --------------------------------------

    def _loop(self) -> None:
        if self._root is None:
            return
        stop = False
        try:
            while True:
                action, arg = self._cmds.get_nowait()
                if action == "show":
                    self._mode = arg
                    if not self._visible:
                        self._visible = True
                        if not self._layered:
                            self._root.deiconify()
                            self._root.attributes("-topmost", True)
                            self._root.lift()
                elif action == "hide":
                    if self._visible:
                        self._visible = False
                        if self._layered:
                            self._need_clear = True
                        else:
                            self._root.withdraw()
                elif action == "stop":
                    stop = True
        except queue.Empty:
            pass
        if stop:
            try:
                self._root.quit()
                self._root.destroy()
            except Exception:
                pass
            return
        try:
            if self._visible:
                self._paint_layered() if self._layered else self._draw_canvas()
            elif self._need_clear:
                self._clear_layered()
                self._need_clear = False
        except Exception as e:
            log.debug("pill draw failed: %s", e)
        self._root.after(40, self._loop)  # ~25 fps
