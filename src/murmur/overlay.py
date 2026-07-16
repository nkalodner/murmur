"""The recording pill: a small always-on-top overlay that shows Murmur is
listening, with live bars that dance to the mic level, like Wispr's.

Built on tkinter (standard library, no extra dependency). tkinter is not
thread-safe, so the Tk root lives entirely on its own thread and the rest of
the app only ever posts commands to a queue that the Tk thread drains from
its own animation loop. Nothing outside that thread touches Tk.

Platform note: on macOS, Tcl/Tk must run on the process main thread, which
pystray's menu-bar loop already occupies, so the two can't coexist. The pill
is therefore Windows + Linux only; macOS falls back to the tray dot. `App`
gates on that before constructing this.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from typing import Callable

log = logging.getLogger("murmur")

WIDTH, HEIGHT = 132, 52
BARS = 9
KEY = "#08090b"  # transparency key color (Windows) / plain background elsewhere
CAPSULE = "#17191d"
BORDER = "#2b2f36"
REC = "#e5484d"
ACCENT = "#38bdf8"
DIM = "#5b6470"


def supported() -> bool:
    # Not macOS (main-thread Tk clash with pystray). Also needs a display.
    return sys.platform != "darwin"


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
            try:
                root.attributes("-alpha", 0.97)
            except tk.TclError:
                pass
            # Knock the rectangle corners out on Windows so the capsule reads
            # as a pill; elsewhere the key color just shows as the background.
            if sys.platform == "win32":
                try:
                    root.attributes("-transparentcolor", KEY)
                except tk.TclError:
                    pass
            root.configure(bg=KEY)
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            x = (sw - WIDTH) // 2
            y = sh - HEIGHT - 96  # float above the dock/taskbar, near the usual cursor spot
            root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{max(0, y)}")

            self._canvas = tk.Canvas(
                root, width=WIDTH, height=HEIGHT, bg=KEY, highlightthickness=0
            )
            self._canvas.pack()
            self._root = root
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
            # Drop Tk references on this thread so the interpreter finalizes
            # them here when the frame unwinds, not from the main thread.
            self._canvas = None
            self._root = None

    def _make_noactivate(self, root) -> None:
        """Stop the overlay from stealing keyboard focus from the target app."""
        try:
            import ctypes

            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            )
        except Exception as e:
            log.debug("pill no-activate failed: %s", e)

    def _loop(self) -> None:
        """Runs on the Tk thread: drain commands, animate, reschedule."""
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
                        self._root.deiconify()
                        self._root.attributes("-topmost", True)
                        self._root.lift()
                elif action == "hide":
                    self._mode = "hidden"
                    if self._visible:
                        self._visible = False
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
                self._draw()
        except Exception as e:
            log.debug("pill draw failed: %s", e)
        self._root.after(40, self._loop)  # ~25 fps, scheduled on the Tk thread

    def _rounded(self, x0, y0, x1, y1, r, **kw) -> None:
        c = self._canvas
        c.create_arc(x0, y0, x0 + 2 * r, y0 + 2 * r, start=90, extent=90, style="pieslice", **kw)
        c.create_arc(x1 - 2 * r, y0, x1, y0 + 2 * r, start=0, extent=90, style="pieslice", **kw)
        c.create_arc(x0, y1 - 2 * r, x0 + 2 * r, y1, start=180, extent=90, style="pieslice", **kw)
        c.create_arc(x1 - 2 * r, y1 - 2 * r, x1, y1, start=270, extent=90, style="pieslice", **kw)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, **kw)
        c.create_rectangle(x0, y0 + r, x1, y1 - r, **kw)

    def _draw(self) -> None:
        import math

        c = self._canvas
        c.delete("all")
        self._rounded(1, 1, WIDTH - 1, HEIGHT - 1, 18, fill=CAPSULE, outline=BORDER, width=1)

        recording = self._mode == "recording"
        self._phase += 0.35
        level = max(0.05, min(1.0, self._level())) if recording else 0.0

        # No text: the red dot means recording, the blue dot means transcribing,
        # and the bars carry the motion.
        dot = REC if recording else ACCENT
        c.create_oval(18, HEIGHT / 2 - 4, 26, HEIGHT / 2 + 4, fill=dot, outline="")

        bx0, mid, bw, gap = 38, HEIGHT / 2, 5, 4
        for i in range(BARS):
            if recording:
                wobble = 0.55 + 0.45 * math.sin(self._phase + i * 0.9)
                target = level * wobble
            else:  # transcribing: a gentle traveling shimmer
                target = 0.25 + 0.22 * math.sin(self._phase * 0.6 + i * 0.7)
            self._bar_h[i] += (target - self._bar_h[i]) * 0.4
            h = max(3.0, self._bar_h[i] * (HEIGHT - 20))
            x = bx0 + i * (bw + gap)
            color = ACCENT if recording else DIM
            c.create_rectangle(x, mid - h / 2, x + bw, mid + h / 2, fill=color, outline="")

