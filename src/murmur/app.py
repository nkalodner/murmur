"""Murmur: hold a key, talk, release, and the words land where your cursor is."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from queue import SimpleQueue

from murmur import __version__
from murmur.config import HISTORY_PATH, Config, load
from murmur.textproc import process

log = logging.getLogger("murmur")


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"  # hotkey held down
    LOCKED = "locked"  # hands-free after a quick tap
    BUSY = "busy"  # transcribing and pasting


TRAY_STATE = {
    State.IDLE: "idle",
    State.RECORDING: "recording",
    State.LOCKED: "recording",
    State.BUSY: "busy",
}


class App:
    def __init__(self, cfg: Config):
        from murmur.audio import Recorder, find_input_device
        from murmur.inject import Injector
        from murmur.sounds import Sounds
        from murmur.transcribe import Transcriber

        self.cfg = cfg
        self._device = find_input_device(cfg.device)
        self.recorder = Recorder(self._device)
        self.transcriber = Transcriber(cfg.model, cfg.quantization, cfg.language)
        self.sounds = Sounds(cfg.sounds)
        self.injector = Injector(cfg.paste, cfg.restore_clipboard_ms, self._hotkey_down)
        self.listener = None  # created in run()
        self.tray = None
        self.settings = None  # SettingsServer, created in run()
        self.settings_url: str | None = None
        self.pill = None  # recording overlay, created in run()
        self._used_pill = False  # a Tk overlay ran in a thread this session

        self._lock = threading.RLock()
        self._state = State.IDLE
        self._press_t = 0.0
        self._max_timer: threading.Timer | None = None
        self._jobs: SimpleQueue = SimpleQueue()
        self._stopping = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop, name="murmur-worker", daemon=True
        )

    # -- helpers --------------------------------------------------------

    def _hotkey_down(self) -> bool:
        return bool(self.listener and self.listener.hotkey_down)

    def _set_state(self, state: State) -> None:
        self._state = state
        if self.tray:
            name = TRAY_STATE[state]
            if state == State.IDLE and not self.transcriber.ready:
                name = "loading"
            self.tray.set_state(name)
        if self.pill:
            if state in (State.RECORDING, State.LOCKED):
                self.pill.show("recording")
            elif state == State.BUSY:
                self.pill.show("transcribing")
            else:
                self.pill.hide()

    def _reconcile_pill(self) -> None:
        """Start or stop the overlay to match cfg.pill. Called outside the
        lock, since Pill.start() waits for its Tk thread to come up."""
        from murmur import overlay

        if self.cfg.pill and overlay.supported() and self.pill is None:
            try:
                pill = overlay.Pill(self.recorder.current_level)
                self.pill = pill if pill.start() else None
            except Exception as e:
                log.debug("recording pill unavailable: %s", e)
                self.pill = None
            if self.pill:
                self._used_pill = True
                with self._lock:
                    self._set_state(self._state)
        elif not self.cfg.pill and self.pill is not None:
            self.pill.stop()
            self.pill = None

    # -- hotkey callbacks (run on the listener thread) --------------------

    def on_press(self) -> None:
        with self._lock:
            if self._stopping.is_set():
                return
            if self._state == State.IDLE:
                self._press_t = time.monotonic()
                self._start_recording()
            elif self._state == State.LOCKED:
                self._finish_recording()
            # RECORDING: duplicate event, ignore. BUSY: wait for the paste.

    def on_release(self) -> None:
        with self._lock:
            if self._state == State.RECORDING:
                held_ms = (time.monotonic() - self._press_t) * 1000
                if held_ms < self.cfg.tap_lock_ms:
                    self._set_state(State.LOCKED)
                    log.info(
                        "Hands-free recording locked. Tap %s again to finish.", self.cfg.hotkey
                    )
                else:
                    self._finish_recording()

    def on_cancel(self) -> None:
        with self._lock:
            if self._state in (State.RECORDING, State.LOCKED):
                self._cancel_max_timer()
                self.recorder.abort()
                self._set_state(State.IDLE)
                self.sounds.play("cancel")
                log.info("Recording canceled")

    # -- recording lifecycle ----------------------------------------------

    def _start_recording(self) -> None:
        try:
            self.recorder.start()
        except Exception as e:
            log.error("Could not open the microphone: %s", e)
            self.sounds.play("error")
            return
        self._set_state(State.RECORDING)
        self.sounds.play("start")
        self._max_timer = threading.Timer(self.cfg.max_seconds, self._on_max_duration)
        self._max_timer.daemon = True
        self._max_timer.start()

    def _on_max_duration(self) -> None:
        with self._lock:
            if self._state in (State.RECORDING, State.LOCKED):
                log.info(
                    "Hit max_seconds (%ss); transcribing what was recorded", self.cfg.max_seconds
                )
                self._finish_recording()

    def _cancel_max_timer(self) -> None:
        if self._max_timer:
            self._max_timer.cancel()
            self._max_timer = None

    def _finish_recording(self) -> None:
        self._cancel_max_timer()
        wav, seconds = self.recorder.stop()
        self.sounds.play("stop")
        if seconds < 0.25:
            self._set_state(State.IDLE)
            return
        self._set_state(State.BUSY)
        self._jobs.put((wav, seconds))

    # -- worker thread -----------------------------------------------------

    def _worker_loop(self) -> None:
        try:
            self.transcriber.load()
            with self._lock:
                self._set_state(self._state)  # refresh the tray away from "loading"
            self.sounds.play("ready")
            log.info("Ready. Hold %s and talk.", self.cfg.hotkey)
        except Exception as e:
            log.error("Model failed to load: %s", e)
            log.error("If the download failed, check your connection and run: murmur --download")
            self.sounds.play("error")
        while True:
            job = self._jobs.get()
            if job is None or self._stopping.is_set():
                break
            wav, seconds = job
            try:
                cfg = self.cfg
                text = process(
                    self.transcriber.transcribe(wav),
                    replacements=cfg.replacements,
                    vocabulary=cfg.vocabulary,
                    vocab_threshold=cfg.vocab_threshold,
                    formatting=cfg.formatting,
                    trailing_space=cfg.trailing_space,
                )
                if text:
                    self.injector.inject(text)
                    self._append_history(seconds, text)
                    log.info("%.1fs of audio -> %d chars", seconds, len(text))
                else:
                    log.info("Heard nothing usable in %.1fs of audio", seconds)
            except Exception:
                log.exception("Transcription failed")
                self.sounds.play("error")
            finally:
                with self._lock:
                    if self._state == State.BUSY:
                        self._set_state(State.IDLE)

    def _append_history(self, seconds: float, text: str) -> None:
        if not self.cfg.history:
            return
        try:
            HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "seconds": round(seconds, 1),
                "text": text.strip(),
            }
            with HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            log.debug("history write failed: %s", e)

    # -- settings (called from the local settings server) ---------------------

    def snapshot(self) -> dict:
        from dataclasses import asdict

        with self._lock:
            state = self._state.value
            model_ready = self.transcriber.ready
            cfg = asdict(self.cfg)
        devices = []
        try:
            from murmur.audio import input_devices

            devices = input_devices()
        except Exception as e:
            log.debug("device listing failed: %s", e)
        from murmur import autostart

        return {
            "state": state,
            "model_ready": model_ready,
            "platform": sys.platform,
            "config": cfg,
            "devices": devices,
            "autostart": autostart.status(),
        }

    def apply_config(self, data: dict) -> list[str]:
        """Merge, validate, and hot-apply a settings change; persists on success.

        Raises ValueError/LookupError with a readable message for bad input.
        """
        from dataclasses import asdict, fields as dc_fields

        from murmur.audio import find_input_device
        from murmur.config import Config, save, validate
        from murmur.hotkey import parse_hotkey

        known = {f.name for f in dc_fields(Config)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {', '.join(sorted(unknown))}")
        warnings: list[str] = []
        with self._lock:
            old = self.cfg
            new = Config(**{**asdict(old), **data})
            validate(new)
            if new.hotkey != old.hotkey:
                parse_hotkey(new.hotkey)
            device_index = self._device
            if new.device != old.device:
                device_index = find_input_device(new.device)

            self.cfg = new
            self.sounds.enabled = new.sounds
            self.injector.paste = new.paste
            self.injector.restore_clipboard_ms = new.restore_clipboard_ms
            if new.device != old.device:
                self._device = device_index
                self.recorder.set_device(device_index)
                if self._state in (State.RECORDING, State.LOCKED):
                    warnings.append("the microphone change applies to the next recording")
            if (new.model, new.quantization, new.language) != (
                old.model,
                old.quantization,
                old.language,
            ):
                from murmur.transcribe import Transcriber

                self.transcriber = Transcriber(new.model, new.quantization, new.language)
                warnings.append(
                    "the model loads on the next dictation, so that one will be slow"
                )
            if new.hotkey != old.hotkey and self.listener is not None:
                if self._state in (State.RECORDING, State.LOCKED):
                    self._finish_recording()
                # In place; recreating the listener here crashes on macOS
                # (see HotkeyListener.retarget).
                self.listener.retarget(new.hotkey)
            self._set_state(self._state)  # refresh the tray title + menu hint
        save(self.cfg)
        self._reconcile_pill()  # start/stop the overlay if cfg.pill changed
        log.info("Settings updated%s", f" ({'; '.join(warnings)})" if warnings else "")
        return warnings

    def test_microphone(self, device_name: str | None) -> dict:
        """Record ~1.4s from a device and report the level, for the settings page."""
        import numpy as np

        from murmur.audio import find_input_device, record_sample

        with self._lock:
            if self._state in (State.RECORDING, State.LOCKED):
                raise ValueError("finish the current recording first, then test the mic")
        index = find_input_device(device_name)  # raises LookupError if not found
        wav, seconds = record_sample(index)
        if seconds <= 0 or not len(wav):
            raise ValueError("no audio captured; is the microphone connected?")
        peak = float(np.max(np.abs(wav)))
        rms = float(np.sqrt(np.mean(wav.astype(np.float64) ** 2)))
        if peak >= 0.06:
            message = "Sounds good. The mic is picking you up clearly."
        elif peak >= 0.012:
            message = "Faint. It hears something, but try speaking up or moving closer."
        else:
            message = "Nearly silent. Check that this is the right mic and it isn't muted."
        return {"ok": True, "peak": round(peak, 4), "rms": round(rms, 4), "message": message}

    def set_autostart(self, enabled: bool) -> dict:
        from murmur import autostart

        if enabled:
            autostart.enable()
        else:
            autostart.disable()
        return autostart.status()

    def open_settings(self) -> None:
        if self.settings_url:
            import webbrowser

            webbrowser.open(self.settings_url)

    # -- lifecycle -----------------------------------------------------------

    def run(self, use_tray: bool = True, open_settings: bool = False) -> None:
        from murmur.hotkey import HotkeyListener

        if sys.platform == "darwin":
            from murmur.macos import preflight

            for problem in preflight():
                log.warning("%s", problem)

        try:
            from murmur.audio import preflight as mic_preflight

            mic_preflight(self._device)
        except Exception as e:
            log.warning("Microphone preflight failed (%s). Is a microphone connected?", e)

        self._worker.start()
        self.listener = HotkeyListener(
            self.cfg.hotkey, self.on_press, self.on_release, self.on_cancel
        )
        self.listener.start()
        log.info(
            "Murmur %s. Hold %s to dictate, quick-tap to go hands-free, Esc cancels.",
            __version__,
            self.cfg.hotkey,
        )

        try:
            from murmur.server import SettingsServer

            self.settings = SettingsServer(self)
            self.settings_url = self.settings.start()
        except Exception as e:
            log.warning("Settings page unavailable: %s", e)
        if self.settings_url:
            log.info("Settings page: %s (also in the tray menu)", self.settings_url)
            if open_settings:
                self.open_settings()

        self._reconcile_pill()

        if use_tray:
            try:
                from murmur.tray import Tray

                self.tray = Tray(
                    lambda: f"Hold {self.cfg.hotkey} to dictate. Tap locks, Esc cancels.",
                    self.shutdown,
                    on_settings=self.open_settings if self.settings_url else None,
                )
            except Exception as e:
                log.warning("Tray unavailable (%s); running without it. Ctrl+C quits.", e)
                self.tray = None
        ran_tray = False
        if self.tray:
            with self._lock:
                self._set_state(self._state)  # sync the initial icon
            try:
                self.tray.run(on_ready=lambda: None)  # blocks the main thread until Quit
                ran_tray = True
            except Exception as e:
                log.warning("Tray failed (%s); running without it. Ctrl+C quits.", e)
                self.tray = None
        if not ran_tray:
            try:
                while not self._stopping.wait(0.5):
                    pass
            except KeyboardInterrupt:
                pass
        self.shutdown()

    def shutdown(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        log.info("Shutting down")
        try:
            if self.listener:
                self.listener.stop()
        except Exception:
            pass
        self.recorder.abort()
        self._jobs.put(None)
        if self.pill:
            self.pill.stop()
        if self.settings:
            self.settings.stop()
        if self.tray:
            self.tray.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="murmur",
        description=(
            "Local push-to-talk dictation with Parakeet. "
            "Hold a key, talk, release; the words land at your cursor."
        ),
    )
    parser.add_argument("--hotkey", help="override the hotkey (default ctrl_r)")
    parser.add_argument(
        "--model", help="override the ASR model (e.g. nemo-parakeet-tdt-0.6b-v3 for multilingual)"
    )
    parser.add_argument("--device", help="input device name substring")
    parser.add_argument("--type", action="store_true", help="type characters instead of pasting")
    parser.add_argument("--no-sounds", action="store_true", help="disable audio cues")
    parser.add_argument(
        "--no-tray", action="store_true", help="run without a tray icon (terminal only)"
    )
    parser.add_argument("--list-devices", action="store_true", help="list input devices and exit")
    parser.add_argument(
        "--settings",
        action="store_true",
        help="open the settings page (starts Murmur first if it isn't running)",
    )
    parser.add_argument("--download", action="store_true", help="download the model and exit")
    parser.add_argument(
        "--enable-autostart",
        action="store_true",
        help="start Murmur automatically at login, then exit",
    )
    parser.add_argument(
        "--disable-autostart", action="store_true", help="stop starting at login, then exit"
    )
    parser.add_argument(
        "--doctor", action="store_true", help="check mic, model, permissions, clipboard and exit"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--version", action="version", version=f"murmur {__version__}")
    args = parser.parse_args(argv)

    # Under the windowless launcher (murmurw / pythonw) there is no console,
    # so stderr is None and console logging would crash on the first message.
    # Fall back to a log file in that case.
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    else:
        try:
            from murmur.config import CONFIG_DIR

            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(CONFIG_DIR / "murmur.log", encoding="utf-8"))
        except OSError:
            handlers.append(logging.NullHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    # -v turns up murmur's own logs without drowning in library debug noise.
    logging.getLogger("murmur").setLevel(logging.DEBUG if args.verbose else logging.INFO)

    cfg = load()
    if args.hotkey:
        cfg.hotkey = args.hotkey
    if args.model:
        cfg.model = args.model
    if args.device:
        cfg.device = args.device
    if args.type:
        cfg.paste = False
    if args.no_sounds:
        cfg.sounds = False

    if args.list_devices:
        from murmur.audio import list_input_devices

        try:
            lines = list_input_devices()
        except Exception as e:
            log.error("Audio backend unavailable: %s", e)
            return 2
        print("\n".join(lines) if lines else "No input devices found.")
        print('* marks the default. Set "device" in ~/.murmur/config.json to a name substring.')
        return 0
    if args.download:
        from murmur.transcribe import Transcriber

        try:
            Transcriber(cfg.model, cfg.quantization, cfg.language).load()
        except Exception as e:
            log.error("Download failed: %s", e)
            log.error("Check your connection and rerun murmur --download; it resumes.")
            return 1
        return 0
    if args.enable_autostart or args.disable_autostart:
        from murmur import autostart

        if not autostart.supported():
            log.error("Start at login is only available on Windows and macOS.")
            return 2
        try:
            autostart.enable() if args.enable_autostart else autostart.disable()
        except Exception as e:
            log.error("%s", e)
            return 1
        print("Murmur will start at login." if args.enable_autostart else "Murmur will no longer start at login.")
        return 0
    if args.doctor:
        from murmur.doctor import run as doctor_run

        return doctor_run(cfg)
    if args.settings:
        from murmur.server import find_running_instance

        url = find_running_instance()
        if url:
            import webbrowser

            webbrowser.open(url)
            print(f"Settings: {url}")
            return 0
        log.info("Murmur is not running yet; starting it now.")

    try:
        app = App(cfg)
    except LookupError as e:
        log.error("%s", e)
        return 2
    try:
        app.run(use_tray=not args.no_tray, open_settings=args.settings)
    except ValueError as e:  # bad hotkey name
        log.error("%s", e)
        return 2
    if app._used_pill:
        # tkinter ran the pill in a background thread; a normal interpreter
        # exit would then finalize Tcl from the main thread and abort with
        # "async handler deleted by the wrong thread". Our own shutdown is
        # already done, so exit hard and skip that finalization.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0
