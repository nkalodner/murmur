"""Turn other audio down while a recording runs, then put it back.

Dictating over a video means the speaker bleeds into the mic and drowns out
your own voice. This lowers the system output volume for the length of a take
and restores the exact level afterward.

Two things shape the design:

- **It never blocks a recording.** Both backends are slow enough to notice
  (macOS shells out to osascript, Windows walks COM), so every change runs on
  a worker thread and `duck()`/`restore()` just post to it. Ordering is kept
  by the queue, so a fast tap still restores after it ducks.
- **It is strictly best-effort.** Anything that throws is logged at debug and
  the take carries on at full volume. Failing to duck must never cost you a
  transcript.

The one hard requirement is that the volume always comes back: `close()`
restores synchronously before the process exits, and a restore with no
saved level is a no-op, so a double restore cannot strand the volume.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from queue import SimpleQueue

log = logging.getLogger("murmur")

# Give the backend a hard ceiling: a wedged osascript or COM call must not
# hold up shutdown (and the volume it would have set is not worth waiting for).
CALL_TIMEOUT = 4.0


def supported() -> bool:
    return sys.platform in ("darwin", "win32")


# ── macOS: osascript ────────────────────────────────────────────────────


def _mac_get() -> float | None:
    out = subprocess.run(
        ["osascript", "-e", "output volume of (get volume settings)"],
        capture_output=True,
        text=True,
        timeout=CALL_TIMEOUT,
    )
    text = out.stdout.strip()
    if out.returncode != 0 or not text.isdigit():
        return None
    return max(0.0, min(1.0, int(text) / 100.0))


def _mac_set(level: float) -> None:
    subprocess.run(
        ["osascript", "-e", f"set volume output volume {round(level * 100)}"],
        capture_output=True,
        timeout=CALL_TIMEOUT,
    )


# ── Windows: IAudioEndpointVolume through ctypes ────────────────────────
# No pywin32/pycaw dependency: we resolve the three COM interfaces by hand.
# Vtable slots are IUnknown's three (QueryInterface/AddRef/Release) followed
# by the interface's own methods in declaration order.

_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"

_RELEASE = 2
_GET_DEFAULT_ENDPOINT = 4  # IMMDeviceEnumerator::GetDefaultAudioEndpoint
_ACTIVATE = 3  # IMMDevice::Activate
_SET_MASTER_SCALAR = 7  # IAudioEndpointVolume::SetMasterVolumeLevelScalar
_GET_MASTER_SCALAR = 9  # IAudioEndpointVolume::GetMasterVolumeLevelScalar

_E_RENDER = 0  # data flow: output
_E_CONSOLE = 0  # role
_CLSCTX_ALL = 23


def _win_guid(text: str):
    import ctypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    guid = GUID()
    ole32 = ctypes.WinDLL("ole32")
    if ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid)) != 0:
        raise OSError(f"bad GUID {text}")
    return guid


def _win_call(ptr, slot: int, restype, argtypes, *args):
    """Invoke one vtable slot on a COM interface pointer."""
    import ctypes

    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtable[slot])(ptr, *args)


class _WinVolume:
    """The default output device's master volume. Open once, reuse."""

    def __init__(self):
        import ctypes

        self._ctypes = ctypes
        self._ole32 = ctypes.WinDLL("ole32")
        # COINIT_APARTMENTTHREADED(2): the audio endpoint objects are happy in
        # an STA and this thread does nothing else. S_FALSE just means this
        # thread was already initialized, which is fine.
        self._ole32.CoInitializeEx(None, 2)
        self._volume = self._open()

    def _open(self):
        ctypes = self._ctypes
        enumerator = ctypes.c_void_p()
        hr = self._ole32.CoCreateInstance(
            ctypes.byref(_win_guid(_CLSID_MMDeviceEnumerator)),
            None,
            _CLSCTX_ALL,
            ctypes.byref(_win_guid(_IID_IMMDeviceEnumerator)),
            ctypes.byref(enumerator),
        )
        if hr != 0 or not enumerator:
            raise OSError(f"CoCreateInstance failed (0x{hr & 0xFFFFFFFF:08x})")
        device = ctypes.c_void_p()
        try:
            hr = _win_call(
                enumerator,
                _GET_DEFAULT_ENDPOINT,
                ctypes.HRESULT,
                (ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)),
                _E_RENDER,
                _E_CONSOLE,
                ctypes.byref(device),
            )
            if hr != 0 or not device:
                raise OSError(f"GetDefaultAudioEndpoint failed (0x{hr & 0xFFFFFFFF:08x})")
        finally:
            _win_call(enumerator, _RELEASE, ctypes.c_ulong, ())
        volume = ctypes.c_void_p()
        try:
            hr = _win_call(
                device,
                _ACTIVATE,
                ctypes.HRESULT,
                (
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p),
                ),
                ctypes.byref(_win_guid(_IID_IAudioEndpointVolume)),
                _CLSCTX_ALL,
                None,
                ctypes.byref(volume),
            )
            if hr != 0 or not volume:
                raise OSError(f"Activate(IAudioEndpointVolume) failed (0x{hr & 0xFFFFFFFF:08x})")
        finally:
            _win_call(device, _RELEASE, ctypes.c_ulong, ())
        return volume

    def get(self) -> float | None:
        ctypes = self._ctypes
        level = ctypes.c_float()
        hr = _win_call(
            self._volume,
            _GET_MASTER_SCALAR,
            ctypes.HRESULT,
            (ctypes.POINTER(ctypes.c_float),),
            ctypes.byref(level),
        )
        if hr != 0:
            return None
        return max(0.0, min(1.0, float(level.value)))

    def set(self, level: float) -> None:
        ctypes = self._ctypes
        _win_call(
            self._volume,
            _SET_MASTER_SCALAR,
            ctypes.HRESULT,
            (ctypes.c_float, ctypes.c_void_p),
            ctypes.c_float(level),
            None,
        )


# ── the ducker ──────────────────────────────────────────────────────────


class Ducker:
    """Lower output volume to `percent` while recording; restore it after."""

    def __init__(self, percent: int = 20):
        self.percent = percent
        self._saved: float | None = None
        self._win: _WinVolume | None = None
        self._jobs: SimpleQueue = SimpleQueue()
        self._idle = threading.Event()
        self._idle.set()
        self._thread = threading.Thread(
            target=self._loop, name="murmur-ducking", daemon=True
        )
        self._thread.start()

    # -- backend calls (worker thread only) ------------------------------

    def _get_volume(self) -> float | None:
        if sys.platform == "darwin":
            return _mac_get()
        if sys.platform == "win32":
            if self._win is None:
                self._win = _WinVolume()
            return self._win.get()
        return None

    def _set_volume(self, level: float) -> None:
        if sys.platform == "darwin":
            _mac_set(level)
        elif sys.platform == "win32":
            if self._win is None:
                self._win = _WinVolume()
            self._win.set(level)

    def _do_duck(self) -> None:
        if self._saved is not None:
            return  # already ducked; keep the original level
        current = self._get_volume()
        if current is None:
            return
        target = max(0.0, min(1.0, self.percent / 100.0))
        if current <= target:
            return  # already quieter than we would make it; leave it alone
        self._set_volume(target)
        self._saved = current

    def _do_restore(self) -> None:
        if self._saved is None:
            return
        level, self._saved = self._saved, None
        self._set_volume(level)

    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            try:
                job()
            except Exception as e:
                # Best-effort by design: a take is worth more than the volume.
                # _do_restore clears _saved before it touches the backend, so a
                # failure here never leaves a level we would try to reapply.
                log.debug("audio ducking failed: %s", e)
            finally:
                if self._jobs.empty():
                    self._idle.set()

    # -- public API (any thread) -----------------------------------------

    def _post(self, job) -> None:
        # Clear before queueing, so a caller that posts then waits cannot see
        # a stale "idle" from before the worker picked the job up.
        self._idle.clear()
        self._jobs.put(job)

    def duck(self) -> None:
        self._post(self._do_duck)

    def restore(self) -> None:
        self._post(self._do_restore)

    def close(self, timeout: float = CALL_TIMEOUT + 1.0) -> None:
        """Restore the volume and stop the worker. Blocks until it is back."""
        self._post(self._do_restore)
        self._jobs.put(None)
        self._thread.join(timeout=timeout)

    def wait_idle(self, timeout: float = CALL_TIMEOUT) -> bool:
        """Block until queued work drains. For tests and shutdown ordering."""
        return self._idle.wait(timeout)
