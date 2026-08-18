"""System tray / menu bar: a microphone that wears the state color, and a
menu that covers the day-to-day without opening the settings page — switch
the mic, paste the last transcript, pause, toggle login, quit."""

from __future__ import annotations

import logging
import sys
from typing import Callable

log = logging.getLogger("murmur")

COLORS = {
    "loading": (138, 143, 152, 130),
    "idle": (138, 143, 152, 255),
    "recording": (229, 72, 77, 255),
    "busy": (245, 165, 36, 255),
    "paused": (138, 143, 152, 95),
}
LABELS = {
    "loading": "loading model",
    "idle": "idle",
    "recording": "recording",
    "busy": "transcribing",
    "paused": "paused",
}


def render_icon(state: str, size: int = 64):
    """The tray mark: the site's mic silhouette (capsule, pickup arc, stem,
    base) in the state color. Drawn 4x and downscaled so the arc stays smooth
    at menu-bar sizes; loading and paused read as the same mic, dimmed."""
    from PIL import Image, ImageDraw

    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = COLORS.get(state, COLORS["idle"])
    u = S / 256  # geometry authored on a 256 grid, scaled to the canvas

    def box(x0, y0, x1, y1):
        return (x0 * u, y0 * u, x1 * u, y1 * u)

    draw.rounded_rectangle(box(103, 38, 153, 138), radius=25 * u, fill=color)
    draw.arc(box(78, 64, 178, 164), start=0, end=180, fill=color, width=int(17 * u))
    draw.rounded_rectangle(box(120, 168, 136, 196), radius=8 * u, fill=color)
    draw.rounded_rectangle(box(88, 198, 168, 214), radius=8 * u, fill=color)
    return img.resize((size, size), Image.LANCZOS)


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
        self._icon = pystray.Icon("murmur", render_icon("loading"), "Murmur", menu)

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
            self._icon.icon = render_icon(state)
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
        try:
            self._icon.stop()
        except Exception:
            pass
