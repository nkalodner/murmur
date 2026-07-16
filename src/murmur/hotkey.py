"""Global hotkey listening via pynput."""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("murmur")

COMMON_KEYS = (
    "ctrl_r, ctrl_l, alt_r, alt_l, alt_gr, cmd, cmd_r, shift_r, shift_l, "
    "f1..f20 (e.g. f8), pause, scroll_lock, insert, home, end, page_up, page_down, menu"
)


def parse_hotkey(name: str):
    """Turn a config string like 'ctrl_r' or 'f8' into a pynput key object."""
    from pynput import keyboard

    n = name.strip().lower()
    if not n:
        raise ValueError("Empty hotkey")
    if len(n) == 1:
        return keyboard.KeyCode.from_char(n)
    try:
        return getattr(keyboard.Key, n)
    except AttributeError:
        raise ValueError(f"Unknown hotkey {name!r}. Try one of: {COMMON_KEYS}") from None


class HotkeyListener:
    """Watches one key globally: press/release drive the app, Esc cancels a recording."""

    def __init__(
        self,
        hotkey: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_cancel: Callable[[], None],
    ):
        from pynput import keyboard

        self._keyboard = keyboard
        self._target = parse_hotkey(hotkey)
        self._on_press = on_press
        self._on_release = on_release
        self._on_cancel = on_cancel
        self._down = False
        # Backends can deliver a trailing event after stop() (X11 does), so
        # gate callbacks on our own flag to make shutdown airtight.
        self._active = True
        self._listener = keyboard.Listener(
            on_press=self._handle_press, on_release=self._handle_release
        )

    @property
    def hotkey_down(self) -> bool:
        return self._down

    def start(self) -> None:
        self._listener.start()
        self._listener.wait()

    def stop(self) -> None:
        self._active = False
        self._listener.stop()

    def retarget(self, hotkey: str) -> None:
        """Watch a different key on the live listener.

        The pynput listener must never be stopped and recreated for a hotkey
        change: a new listener builds its keyboard-layout context through
        TIS/HIToolbox on the fresh listener thread, and once the AppKit tray
        loop owns the process macOS kills it with SIGTRAP for calling those
        APIs off the main thread. Swapping the target key is pure Python and
        safe from any thread.
        """
        self._target = parse_hotkey(hotkey)  # raises before mutating state
        self._down = False

    def _matches(self, key) -> bool:
        if key == self._target:
            return True
        try:
            canon = self._listener.canonical(key)
        except Exception:
            return False
        if canon == self._target:
            return True
        kc = self._keyboard.KeyCode
        if (
            isinstance(self._target, kc)
            and isinstance(canon, kc)
            and self._target.char
            and canon.char
        ):
            return canon.char.lower() == self._target.char.lower()
        return False

    def _handle_press(self, key) -> None:
        if not self._active:
            return
        try:
            if self._matches(key):
                if not self._down:  # ignore OS key repeat while held
                    self._down = True
                    self._on_press()
            elif key == self._keyboard.Key.esc:
                self._on_cancel()
        except Exception:
            log.exception("hotkey press handler failed")

    def _handle_release(self, key) -> None:
        if not self._active:
            return
        try:
            if self._matches(key):
                if self._down:
                    self._down = False
                    self._on_release()
        except Exception:
            log.exception("hotkey release handler failed")
