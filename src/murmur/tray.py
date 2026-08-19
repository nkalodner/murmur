"""System tray / menu bar: a microphone that wears the state color, and a
menu that covers the day-to-day without opening the settings page — switch
the mic, paste the last transcript, pause, toggle login, quit."""

from __future__ import annotations

import logging
import sys
from typing import Callable

log = logging.getLogger("murmur")

# Idle is bar-colored ink: white on a dark macOS menu bar or Windows taskbar,
# near-black on a light one (system_theme decides). The states keep their
# colors on either bar, and the dimmed states are the ink at lower alpha.
COLORS = {
    "loading": (235, 236, 240, 130),
    "idle": (235, 236, 240, 255),
    "recording": (229, 72, 77, 255),
    "busy": (245, 165, 36, 255),
    "paused": (235, 236, 240, 95),
}
LIGHT_INK = (58, 60, 64)
_INK_STATES = ("idle", "loading", "paused")


def system_theme() -> str:
    """The bar the icon sits on: "dark" or "light". Unknown reads as dark,
    which keeps the white ink, so a detection failure never blanks the icon
    on the common dark bar."""
    try:
        if sys.platform == "darwin":
            import subprocess

            # The global AppleInterfaceStyle key exists only in dark mode;
            # in light mode the read errors out.
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2,
            )
            return "dark" if out.returncode == 0 and "Dark" in out.stdout else "light"
        if sys.platform == "win32":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                light, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return "light" if light else "dark"
    except Exception as e:
        log.debug("theme detection failed: %s", e)
    return "dark"


def _color(state: str, theme: str):
    c = COLORS.get(state, COLORS["idle"])
    if theme == "light" and state in _INK_STATES:
        c = (*LIGHT_INK, c[3])
    return c
LABELS = {
    "loading": "loading model",
    "idle": "idle",
    "recording": "recording",
    "busy": "transcribing",
    "paused": "paused",
}


def render_icon(state: str, size: int = 64, theme: str = "dark"):
    """The tray mark: a retro broadcast mic in the state color — slatted
    capsule, cradle arc, stem, base, one sound wave off each side. Drawn 4x on
    a 256 grid and downscaled so the curves stay smooth at menu-bar sizes;
    loading and paused read as the same mic, dimmed. The slats are punched
    through the capsule's alpha so they stay crisp on any background."""
    import numpy as np
    from PIL import Image, ImageDraw

    S = size * 4
    u = S / 256  # geometry authored on a 256 grid, scaled to the canvas
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    white = (255, 255, 255, 255)

    def box(x0, y0, x1, y1):
        return (x0 * u, y0 * u, x1 * u, y1 * u)

    draw.rounded_rectangle(box(100, 34, 156, 142), radius=28 * u, fill=white)
    draw.arc(box(76, 62, 180, 166), start=0, end=180, fill=white, width=int(17 * u))
    draw.rounded_rectangle(box(120, 170, 136, 198), radius=8 * u, fill=white)
    draw.rounded_rectangle(box(86, 200, 170, 216), radius=8 * u, fill=white)
    # one wave per side, centered on the capsule; two per side smear at 22px
    cx, cy, r = 128, 88, 86
    for a0, a1 in ((-28, 28), (152, 208)):
        draw.arc(box(cx - r, cy - r, cx + r, cy + r), start=a0, end=a1,
                 fill=white, width=int(13 * u))
    arr = np.array(layer)
    for y in (58, 79, 100, 121):  # the retro slats, capsule-width only
        arr[int((y - 4) * u):int((y + 4) * u), int(106 * u):int(150 * u), 3] = 0
    img = Image.fromarray(arr).resize((size, size), Image.LANCZOS)
    color = _color(state, theme)
    out = np.array(img).astype(np.uint16)
    out[:, :, 0], out[:, :, 1], out[:, :, 2] = color[0], color[1], color[2]
    out[:, :, 3] = out[:, :, 3] * color[3] // 255
    return Image.fromarray(out.astype(np.uint8))


class Tray:
    def __init__(
        self,
        hint: Callable[[], str] | str,
        on_quit: Callable[[], None],
        on_settings: Callable[[], None] | None = None,
        mic_choices: Callable[[], list[tuple[str, bool, Callable[[], None]]]] | None = None,
        last_transcript: Callable[[], str | None] | None = None,
        on_paste_last: Callable[[], None] | None = None,
        is_paused: Callable[[], bool] | None = None,
        on_toggle_pause: Callable[[], None] | None = None,
        autostart_state: Callable[[], dict] | None = None,
        on_toggle_autostart: Callable[[], None] | None = None,
        update_available: Callable[[], bool] | None = None,
    ):
        import pystray

        self._state = "loading"
        self._theme = system_theme()
        self._on_quit = on_quit
        self._on_settings = on_settings
        hint_text = hint if callable(hint) else (lambda: str(hint))
        items = [
            pystray.MenuItem(
                lambda item: f"Murmur: {LABELS.get(self._state, self._state)}",
                None,
                enabled=False,
            ),
            pystray.MenuItem(lambda item: hint_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
        ]
        if on_settings is not None:
            # default=True makes double-clicking the tray icon open it.
            items.append(pystray.MenuItem("Settings...", self._settings, default=True))
        if on_paste_last is not None and last_transcript is not None:
            items.append(
                pystray.MenuItem(
                    "Paste last transcript",
                    self._wrap(on_paste_last, "paste last"),
                    enabled=lambda item: bool(last_transcript()),
                )
            )
        if mic_choices is not None:
            # Rebuilt every time the menu opens, so a mic plugged in after
            # launch shows up without a rescan.
            def mic_items():
                for label, selected, pick in mic_choices():
                    yield pystray.MenuItem(
                        label,
                        self._wrap(pick, "switch mic"),
                        checked=(lambda item, sel=selected: sel),
                        radio=True,
                    )

            items.append(pystray.MenuItem("Microphone", pystray.Menu(mic_items)))
        toggles = []
        if on_toggle_pause is not None and is_paused is not None:
            toggles.append(
                pystray.MenuItem(
                    "Pause dictation",
                    self._wrap(on_toggle_pause, "toggle pause"),
                    checked=lambda item: is_paused(),
                )
            )
        if on_toggle_autostart is not None and autostart_state is not None:
            toggles.append(
                pystray.MenuItem(
                    "Start at login",
                    self._wrap(on_toggle_autostart, "toggle autostart"),
                    checked=lambda item: bool(autostart_state().get("enabled")),
                    visible=lambda item: bool(autostart_state().get("supported")),
                )
            )
        if toggles:
            items += [pystray.Menu.SEPARATOR, *toggles]
        if update_available is not None and on_settings is not None:
            items.append(
                pystray.MenuItem(
                    "Update available - open Settings",
                    self._settings,
                    visible=lambda item: bool(update_available()),
                )
            )
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Quit Murmur", self._quit)]
        menu = pystray.Menu(*items)
        self._icon = pystray.Icon("murmur", render_icon("loading", theme=self._theme), "Murmur", menu)
        # The bar can flip light/dark mid-session (manual toggle, or Auto
        # appearance at sunset). A slow poll keeps the ink matched; only a
        # real flip re-renders. Off the recording path entirely.
        if sys.platform in ("darwin", "win32"):
            import threading

            self._theme_stop = threading.Event()

            def watch_theme():
                while not self._theme_stop.wait(15):
                    theme = system_theme()
                    if theme != self._theme:
                        self._theme = theme
                        self.set_state(self._state)

            threading.Thread(target=watch_theme, name="murmur-theme", daemon=True).start()
        else:
            self._theme_stop = None

    def _wrap(self, fn: Callable[[], None], what: str):
        def handler(icon, item):
            try:
                fn()
            except Exception as e:
                log.warning("%s failed: %s", what, e)
            try:
                icon.update_menu()
            except Exception:
                pass

        return handler

    def _settings(self, icon, item) -> None:
        try:
            if self._on_settings:
                self._on_settings()
        except Exception as e:
            log.debug("open settings failed: %s", e)

    def _quit(self, icon, item) -> None:
        try:
            self._on_quit()
        finally:
            icon.stop()

    def set_state(self, state: str) -> None:
        self._state = state
        try:
            self._icon.icon = render_icon(state, theme=self._theme)
            self._icon.title = f"Murmur: {LABELS.get(state, state)}"
            self._icon.update_menu()
        except Exception as e:
            log.debug("tray update failed: %s", e)

    def run(self, on_ready: Callable[[], None]) -> None:
        """Blocks the calling thread until Quit. macOS requires this on the main thread."""
        if sys.platform == "darwin":
            # Menu-bar app only: without this the AppKit loop puts a "Python"
            # icon in the Dock. Must run on the main thread before icon.run().
            try:
                import AppKit

                AppKit.NSApplication.sharedApplication().setActivationPolicy_(
                    AppKit.NSApplicationActivationPolicyAccessory
                )
            except Exception as e:
                log.debug("could not hide the Dock icon: %s", e)

        def setup(icon):
            icon.visible = True
            on_ready()

        self._icon.run(setup=setup)

    def stop(self) -> None:
        if self._theme_stop is not None:
            self._theme_stop.set()
        try:
            self._icon.stop()
        except Exception:
            pass
