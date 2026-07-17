"""Put transcribed text into the focused app: clipboard paste (default) or typing."""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable

log = logging.getLogger("murmur")


class Injector:
    def __init__(
        self,
        paste: bool = True,
        restore_clipboard_ms: int = 600,
        hotkey_down: Callable[[], bool] = lambda: False,
    ):
        self.paste = paste
        self.restore_clipboard_ms = restore_clipboard_ms
        self._hotkey_down = hotkey_down

    def inject(self, text: str) -> None:
        if not text:
            return
        # If the stop tap is still physically held, wait so a stray modifier
        # can't mangle the paste shortcut.
        deadline = time.monotonic() + 1.0
        while self._hotkey_down() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.05)
        if self.paste:
            self._paste(text)
        else:
            self._type(text)

    def _paste(self, text: str) -> None:
        import pyperclip
        from pynput import keyboard

        previous: str | None
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None
        pyperclip.copy(text)
        time.sleep(0.08)  # let the clipboard settle before the paste keystroke
        kb = keyboard.Controller()
        modifier = keyboard.Key.cmd if sys.platform == "darwin" else keyboard.Key.ctrl
        with kb.pressed(modifier):
            kb.tap("v")
        if previous is not None and self.restore_clipboard_ms >= 0:

            def restore(value: str = previous, mine: str = text) -> None:
                try:
                    # Only put the old clipboard back if nothing new was copied
                    # while we held it; otherwise we'd clobber the fresh copy.
                    if pyperclip.paste() == mine:
                        pyperclip.copy(value)
                except Exception as e:
                    log.debug("clipboard restore failed: %s", e)

            timer = threading.Timer(self.restore_clipboard_ms / 1000.0, restore)
            timer.daemon = True
            timer.start()

    def _type(self, text: str) -> None:
        from pynput import keyboard

        keyboard.Controller().type(text)
