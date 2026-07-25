"""Global hotkey listening via pynput.

A binding is either one key ("ctrl_r") or a chord of keys held together
("cmd+shift"). The app watches up to two of them: the primary hotkey and an
optional second one, so a chord can trigger dictation without giving up the
plain key.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("murmur")

COMMON_KEYS = (
    "ctrl_r, ctrl_l, alt_r, alt_l, alt_gr, cmd, cmd_r, shift_r, shift_l, "
    "f1..f20 (e.g. f8), pause, scroll_lock, insert, home, end, page_up, page_down, menu"
)

CHORD_SEP = "+"
MAX_CHORD_KEYS = 3


def split_binding(spec: str) -> list[str]:
    """'cmd+shift' -> ['cmd', 'shift']. Pure string work, no pynput needed."""
    text = spec.strip().lower()
    if not text:
        raise ValueError("Empty hotkey")
    if text == CHORD_SEP:  # the '+' key itself, not a separator
        return [CHORD_SEP]
    parts = [p.strip() for p in text.split(CHORD_SEP)]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("Empty hotkey")
    if len(parts) > MAX_CHORD_KEYS:
        raise ValueError(f"A hotkey can combine at most {MAX_CHORD_KEYS} keys")
    if len(set(parts)) != len(parts):
        raise ValueError(f"{spec!r} lists the same key twice")
    return parts


def parse_hotkey(name: str):
    """Turn one key name like 'ctrl_r' or 'f8' into a pynput key object."""
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


def _same_key(target, key) -> bool:
    from pynput import keyboard

    if key == target:
        return True
    kc = keyboard.KeyCode
    if isinstance(target, kc) and isinstance(key, kc) and target.char and key.char:
        return key.char.lower() == target.char.lower()
    return False


class Binding:
    """One hotkey: a single key, or several that must be held together."""

    def __init__(self, spec: str):
        self.spec = spec.strip().lower()
        self.keys = [parse_hotkey(part) for part in split_binding(spec)]
        self._down = [False] * len(self.keys)

    @property
    def complete(self) -> bool:
        """Every key of this binding is currently held."""
        return all(self._down)

    @property
    def any_down(self) -> bool:
        """At least one key is still physically held."""
        return any(self._down)

    def reset(self) -> None:
        self._down = [False] * len(self.keys)

    def press(self, key, canonical) -> tuple[bool, bool]:
        """Record a key going down.

        Returns (belongs_to_this_binding, just_became_complete).
        """
        was = self.complete
        matched = False
        for i, target in enumerate(self.keys):
            if _same_key(target, key) or (canonical is not None and _same_key(target, canonical)):
                matched = True
                self._down[i] = True
        return matched, (not was and self.complete)

    def release(self, key, canonical) -> bool:
        """Record a key going up; True if a complete chord just broke."""
        was = self.complete
        for i, target in enumerate(self.keys):
            if _same_key(target, key) or (canonical is not None and _same_key(target, canonical)):
                self._down[i] = False
        return was and not self.complete


class HotkeyListener:
    """Watches the hotkeys globally: press/release drive the app, Esc cancels."""

    def __init__(
        self,
        hotkey: str,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_cancel: Callable[[], None],
        hotkey2: str | None = None,
    ):
        from pynput import keyboard

        self._keyboard = keyboard
        self._bindings = self._build(hotkey, hotkey2)
        self._active: Binding | None = None  # the one currently recording
        self._on_press = on_press
        self._on_release = on_release
        self._on_cancel = on_cancel
        # Backends can deliver a trailing event after stop() (X11 does), so
        # gate callbacks on our own flag to make shutdown airtight.
        self._active_listener = True
        self._listener = keyboard.Listener(
            on_press=self._handle_press, on_release=self._handle_release
        )

    @staticmethod
    def _build(hotkey: str, hotkey2: str | None) -> list[Binding]:
        bindings = [Binding(hotkey)]
        if hotkey2 and hotkey2.strip():
            bindings.append(Binding(hotkey2))
        return bindings

    @property
    def hotkey_down(self) -> bool:
        """True while any hotkey key is still held.

        The injector waits on this before pasting, so it deliberately stays
        true until every key of a chord is up: pasting with a modifier still
        held would mangle the Cmd/Ctrl+V shortcut.
        """
        return any(b.any_down for b in self._bindings)

    def start(self) -> None:
        self._listener.start()
        self._listener.wait()

    def stop(self) -> None:
        self._active_listener = False
        self._listener.stop()

    def retarget(self, hotkey: str, hotkey2: str | None = None) -> None:
        """Watch different keys on the live listener.

        The pynput listener must never be stopped and recreated for a hotkey
        change: a new listener builds its keyboard-layout context through
        TIS/HIToolbox on the fresh listener thread, and once the AppKit tray
        loop owns the process macOS kills it with SIGTRAP for calling those
        APIs off the main thread. Swapping the bindings is pure Python and
        safe from any thread.
        """
        bindings = self._build(hotkey, hotkey2)  # raises before mutating state
        self._bindings = bindings
        self._active = None

    def _canonical(self, key):
        try:
            return self._listener.canonical(key)
        except Exception:
            return None

    def _handle_press(self, key) -> None:
        if not self._active_listener:
            return
        try:
            canonical = self._canonical(key)
            matched_any = False
            completed: Binding | None = None
            for binding in self._bindings:
                matched, complete = binding.press(key, canonical)
                matched_any = matched_any or matched
                if complete and completed is None:
                    completed = binding
            if completed is not None:
                if self._active is None:  # ignore a second binding mid-take
                    self._active = completed
                    self._on_press()
            elif not matched_any and key == self._keyboard.Key.esc:
                self._on_cancel()
        except Exception:
            log.exception("hotkey press handler failed")

    def _handle_release(self, key) -> None:
        if not self._active_listener:
            return
        try:
            canonical = self._canonical(key)
            for binding in self._bindings:
                broke = binding.release(key, canonical)
                if broke and self._active is binding:
                    self._active = None
                    self._on_release()
        except Exception:
            log.exception("hotkey release handler failed")
