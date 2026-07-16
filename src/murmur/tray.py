"""System tray / menu bar icon: gray idle, red recording, amber working."""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("murmur")

COLORS = {
    "loading": (138, 143, 152, 130),
    "idle": (138, 143, 152, 255),
    "recording": (229, 72, 77, 255),
    "busy": (245, 165, 36, 255),
}
LABELS = {
    "loading": "loading model",
    "idle": "idle",
    "recording": "recording",
    "busy": "transcribing",
}


def _image(state: str):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = COLORS.get(state, COLORS["idle"])
    if state == "loading":
        draw.ellipse((12, 12, 52, 52), outline=color, width=6)
    else:
        draw.ellipse((12, 12, 52, 52), fill=color)
    return img


class Tray:
    def __init__(self, hotkey: str, on_quit: Callable[[], None]):
        import pystray

        self._state = "loading"
        self._on_quit = on_quit
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: f"Murmur: {LABELS.get(self._state, self._state)}",
                None,
                enabled=False,
            ),
            pystray.MenuItem(
                f"Hold {hotkey} to dictate. Tap locks, Esc cancels.", None, enabled=False
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Murmur", self._quit),
        )
        self._icon = pystray.Icon("murmur", _image("loading"), "Murmur", menu)

    def _quit(self, icon, item) -> None:
        try:
            self._on_quit()
        finally:
            icon.stop()

    def set_state(self, state: str) -> None:
        self._state = state
        try:
            self._icon.icon = _image(state)
            self._icon.title = f"Murmur: {LABELS.get(state, state)}"
            self._icon.update_menu()
        except Exception as e:
            log.debug("tray update failed: %s", e)

    def run(self, on_ready: Callable[[], None]) -> None:
        """Blocks the calling thread until Quit. macOS requires this on the main thread."""

        def setup(icon):
            icon.visible = True
            on_ready()

        self._icon.run(setup=setup)

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
