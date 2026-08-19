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
        self.sounds = Sounds(cfg.sounds, cfg.sound_volume / 100, cfg.mute_start_cue)
        self.injector = Injector(cfg.paste, cfg.restore_clipboard_ms, self._hotkey_down)
        self.listener = None  # created in run()
        self.tray = None
        self.settings = None  # SettingsServer, created in run()
        self.settings_url: str | None = None
        self.pill = None  # recording overlay, created in run()
        self._used_pill = False  # a Tk overlay ran in a thread this session
        self.ducker = None  # lowers other audio while recording, created on demand

        self._lock = threading.RLock()
        self._state = State.IDLE
        self._paused = False  # tray toggle: hotkeys ignored until unpaused
        self._press_t = 0.0
        self._max_timer: threading.Timer | None = None
        self._jobs: SimpleQueue = SimpleQueue()
        self._stopping = threading.Event()
        # macOS grants as they stood when the hotkey listener started; the
        # settings page compares against the live status to say "granted,
        # now quit and reopen" at exactly the right moment.
        self._perms_at_start: dict = {}
        self._worker = threading.Thread(
            target=self._worker_loop, name="murmur-worker", daemon=True
        )

    # -- helpers --------------------------------------------------------

    def _hotkey_down(self) -> bool:
        return bool(self.listener and self.listener.hotkey_down)

    def _hotkey_label(self) -> str:
        """How the hotkeys read in logs and the tray. Either slot may be off."""
        from murmur.config import hotkey_specs

        return " or ".join(hotkey_specs(self.cfg)) or "no hotkey"

    def _set_state(self, state: State) -> None:
        self._state = state
        if self.tray:
            name = TRAY_STATE[state]
            if state == State.IDLE and not self.transcriber.ready:
                name = "loading"
            if state == State.IDLE and self._paused:
                name = "paused"
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

    def _reconcile_ducker(self) -> None:
        """Start or drop the audio ducker to match cfg. Called outside the lock."""
        from murmur import ducking

        if self.cfg.duck_audio and ducking.supported():
            if self.ducker is None:
                try:
                    self.ducker = ducking.Ducker(self.cfg.duck_percent)
                except Exception as e:
                    log.debug("audio ducking unavailable: %s", e)
                    self.ducker = None
            else:
                self.ducker.percent = self.cfg.duck_percent
        elif self.ducker is not None:
            # Turning it off mid-session must put the volume back.
            self.ducker.close()
            self.ducker = None

    # -- hotkey callbacks (run on the listener thread) --------------------

    def on_press(self) -> None:
        with self._lock:
            if self._stopping.is_set() or self._paused:
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
                        "Hands-free recording locked. Tap %s again to finish.", self._hotkey_label()
                    )
                else:
                    self._finish_recording()

    def on_cancel(self) -> None:
        with self._lock:
            if self._state in (State.RECORDING, State.LOCKED):
                self._cancel_max_timer()
                self.recorder.abort()
                if self.ducker:
                    self.ducker.restore()
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
        # The mic is already open, so without this the take starts with
        # Murmur's own chime and the model types "mm". Mute up front in case
        # the cue sounds immediately, then re-anchor from the moment playback
        # really begins, so the window covers the chime and little else.
        # The up-front guard also bounds how late a player may start: past
        # that (a many-times-normal afplay spawn) a sliver of the chime's
        # fade-in can survive, which is far too quiet to transcribe.
        bleed = self.sounds.bleed_seconds("start")
        self.recorder.mute_for(bleed)
        self.sounds.play("start", on_audible=lambda: self.recorder.mute_for(bleed))
        # After the cue, so the confirmation chime is not the thing we duck.
        if self.ducker:
            self.ducker.duck()
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
        if self.ducker:
            self.ducker.restore()
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
            log.info("Ready. Hold %s and talk.", self._hotkey_label())
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
                    format_bare_times=cfg.format_bare_times,
                    format_acronyms=cfg.format_acronyms,
                    remove_fillers=cfg.remove_fillers,
                    filler_words=cfg.filler_words,
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
        from murmur import autostart, updates
        from murmur.models import KNOWN_MODELS

        from murmur.macos import permission_status, restart_needed

        perms = permission_status()
        return {
            "state": state,
            "model_ready": model_ready,
            "platform": sys.platform,
            "config": cfg,
            "devices": devices,
            "autostart": autostart.status(),
            # Cache only; the network check runs on its own thread at startup.
            "update": updates.status(),
            # The curated menu the settings page renders its picker from.
            "models": [asdict(m) for m in KNOWN_MODELS],
            # Live macOS grants, plus whether a grant arrived after the hotkey
            # listener started (which leaves it dead until Murmur reopens).
            # The page polls this, so the banner flips the moment a toggle does.
            "permissions": {
                "relevant": sys.platform == "darwin",
                **perms,
                "restart_needed": restart_needed(self._perms_at_start, perms),
            },
        }

    def apply_config(self, data: dict) -> list[str]:
        """Merge, validate, and hot-apply a settings change; persists on success.

        Raises ValueError/LookupError with a readable message for bad input.
        """
        from dataclasses import asdict, fields as dc_fields

        from murmur.audio import find_input_device
        from murmur.config import Config, save, validate
        from murmur.ducking import supported as ducking_supported
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
            if new.model != old.model:
                # Catch a name onnx-asr would refuse NOW, not on the next
                # dictation (which would just quietly fail to load).
                from murmur.models import check_model_name

                problem = check_model_name(new.model)
                if problem:
                    raise ValueError(problem)
            if (new.hotkey, new.hotkey2) != (old.hotkey, old.hotkey2):
                # Reject an unknown key name now, while the old binding is
                # still live, instead of breaking the listener on retarget.
                from murmur.hotkey import split_binding

                for spec in (new.hotkey, new.hotkey2):
                    if spec and spec.strip():
                        for part in split_binding(spec):
                            parse_hotkey(part)
            device_index = self._device
            if new.device != old.device:
                device_index = find_input_device(new.device)

            self.cfg = new
            self.sounds.enabled = new.sounds
            self.sounds.volume = new.sound_volume / 100
            self.sounds.mute_start = new.mute_start_cue
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
            if (new.hotkey, new.hotkey2) != (old.hotkey, old.hotkey2) and self.listener is not None:
                if self._state in (State.RECORDING, State.LOCKED):
                    self._finish_recording()
                # In place; recreating the listener here crashes on macOS
                # (see HotkeyListener.retarget).
                self.listener.retarget(new.hotkey, new.hotkey2)
            if new.duck_audio and not ducking_supported():
                warnings.append("quieting other audio is only available on macOS and Windows")
            self._set_state(self._state)  # refresh the tray title + menu hint
        save(self.cfg)
        self._reconcile_pill()  # start/stop the overlay if cfg.pill changed
        self._reconcile_ducker()  # start/stop/retune ducking if it changed
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

    # -- dictionary transfer (settings page Export/Import) ----------------

    def dictionary_export(self) -> dict:
        from murmur.config import dictionary_payload

        with self._lock:
            return dictionary_payload(self.cfg)

    def dictionary_import(self, data: dict) -> dict:
        """Merge an uploaded dictionary file into the live config.

        Raises ValueError with a readable message on a bad payload. The
        dictionary applies to the very next transcript — textproc reads
        cfg fresh each time, so nothing needs reloading.
        """
        from murmur.config import extract_dictionary, merge_dictionary, save

        vocab, repl = extract_dictionary(data)
        with self._lock:
            words, pairs = merge_dictionary(self.cfg, vocab, repl)
            if words or pairs:
                save(self.cfg)
            return {
                "ok": True,
                "added_words": words,
                "added_pairs": pairs,
                "total_words": len(self.cfg.vocabulary),
                "total_pairs": len(self.cfg.replacements),
            }

    def toggle_pause(self) -> None:
        """Tray: stop listening to the hotkeys until toggled back."""
        with self._lock:
            if not self._paused and self._state in (State.RECORDING, State.LOCKED):
                # Pausing mid-take throws the take away; pause means "stop".
                self._cancel_max_timer()
                self.recorder.abort()
                if self.ducker:
                    self.ducker.restore()
                self._state = State.IDLE
            self._paused = not self._paused
            self._set_state(self._state)
        log.info("Dictation %s", "paused" if self._paused else "resumed")

    def is_paused(self) -> bool:
        return self._paused

    def pick_microphone(self, name: str | None) -> None:
        """Tray: switch input device; persists like a settings-page save."""
        self.apply_config({"device": name})

    def tray_mic_choices(self) -> list[tuple[str, bool, "object"]]:
        from murmur.audio import input_devices

        try:
            devices = input_devices()
        except Exception as e:
            log.debug("device listing failed: %s", e)
            devices = []
        return [
            (label, selected, (lambda v=value: self.pick_microphone(v)))
            for label, selected, value in mic_choices(devices, self.cfg.device)
        ]

    def paste_last_transcript(self) -> None:
        """Tray: re-inject the newest saved dictation at the cursor."""
        text = last_transcript()
        if not text:
            log.info("No transcript to paste yet")
            return
        self.injector.inject(text + (" " if self.cfg.trailing_space else ""))
        log.info("Pasted the last transcript (%d chars)", len(text))

    def open_settings(self) -> None:
        if self.settings_url:
            import webbrowser

            webbrowser.open(self.settings_url)

    # -- lifecycle -----------------------------------------------------------

    def _watch_permissions(self) -> None:
        """Poll for macOS grants that were missing at launch and say, the
        moment one lands, whether it works now or needs a restart first.
        Runs as a daemon thread; exits once nothing is left to watch."""
        from murmur.macos import permission_status

        waiting = {k for k, v in self._perms_at_start.items() if v is False}
        while waiting and not self._stopping.wait(3):
            now = permission_status()
            if "input_monitoring" in waiting and now.get("input_monitoring"):
                waiting.discard("input_monitoring")
                log.warning(
                    "Input Monitoring is granted now. One more step: quit Murmur and "
                    "start it again. The hotkey only attaches at launch, so this copy "
                    "cannot see it yet."
                )
            if "accessibility" in waiting and now.get("accessibility"):
                waiting.discard("accessibility")
                log.warning("Accessibility is granted now. Pasting works from here; no restart needed.")

    def run(self, use_tray: bool = True, open_settings: bool = False) -> None:
        from murmur.hotkey import HotkeyListener

        if sys.platform == "darwin":
            from murmur.macos import permission_status, preflight

            # Before the listener exists: this snapshot is what "the hotkey
            # attached without Input Monitoring" is judged against.
            self._perms_at_start = permission_status()
            for problem in preflight():
                log.warning("%s", problem)
            if any(v is False for v in self._perms_at_start.values()):
                threading.Thread(
                    target=self._watch_permissions, name="murmur-perms", daemon=True
                ).start()

        try:
            from murmur.audio import preflight as mic_preflight

            mic_preflight(self._device)
        except Exception as e:
            log.warning("Microphone preflight failed (%s). Is a microphone connected?", e)

        self._worker.start()
        self.listener = HotkeyListener(
            self.cfg.hotkey,
            self.on_press,
            self.on_release,
            self.on_cancel,
            hotkey2=self.cfg.hotkey2,
        )
        self.listener.start()
        log.info(
            "Murmur %s. Hold %s to dictate, quick-tap to go hands-free, Esc cancels.",
            __version__,
            self._hotkey_label(),
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
        self._reconcile_ducker()
        if self.cfg.update_check:
            from murmur import updates

            updates.check_in_background()

        if use_tray:
            try:
                from murmur import autostart, updates
                from murmur.tray import Tray

                self.tray = Tray(
                    lambda: f"Hold {self._hotkey_label()} to dictate",
                    self.shutdown,
                    on_settings=self.open_settings if self.settings_url else None,
                    mic_choices=self.tray_mic_choices,
                    last_transcript=last_transcript,
                    on_paste_last=self.paste_last_transcript,
                    is_paused=self.is_paused,
                    on_toggle_pause=self.toggle_pause,
                    autostart_state=autostart.status,
                    on_toggle_autostart=lambda: self.set_autostart(
                        not autostart.status().get("enabled")
                    ),
                    update_available=lambda: bool(updates.status().get("available")),
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
        if self.ducker:
            # Blocks until the volume is back: main() may os._exit() right
            # after this, and a daemon thread would not get another turn.
            self.ducker.close()
            self.ducker = None
        if self.pill:
            self.pill.stop()
        if self.settings:
            self.settings.stop()
        if self.tray:
            self.tray.stop()


def last_transcript() -> str | None:
    """The newest saved dictation, for the tray's Paste last transcript."""
    from murmur.server import read_history_tail

    entries = read_history_tail(1)
    text = (entries[0].get("text") or "").strip() if entries else ""
    return text or None


def mic_choices(devices: list[dict], current: str | None) -> list[tuple[str, bool, str | None]]:
    """(label, selected, config value) rows for the tray's Microphone menu.

    Pure so it is testable: the system default leads, the configured device
    stays listed (marked) even when it is unplugged right now.
    """
    default = next((d["name"] for d in devices if d.get("default")), None)
    rows: list[tuple[str, bool, str | None]] = [
        (f"System default{f' ({default})' if default else ''}", not current, None)
    ]
    seen = False
    for d in devices:
        selected = bool(current) and current == d["name"]
        seen = seen or selected
        rows.append((d["name"], selected, d["name"]))
    if current and not seen:
        rows.append((f"{current} (not found)", True, current))
    return rows


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


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
        "--hotkey2",
        help="a second hotkey that also starts dictation; may combine keys with + (e.g. cmd+shift)",
    )
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
        "--export-dictionary",
        nargs="?",
        const="murmur-dictionary.json",
        metavar="FILE",
        help="write your vocabulary + replacements to FILE "
        "(default murmur-dictionary.json) for another device, then exit",
    )
    parser.add_argument(
        "--import-dictionary",
        metavar="FILE",
        help="merge vocabulary + replacements from an exported FILE into "
        "this machine's dictionary, then exit",
    )
    parser.add_argument(
        "--doctor", action="store_true", help="check mic, model, permissions, clipboard and exit"
    )
    parser.add_argument(
        "--check-update",
        action="store_true",
        help="ask GitHub whether a newer Murmur exists, then exit",
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

    # Dictionary transfer runs on the freshly-loaded config, before any
    # CLI overrides touch it — an import must never persist a --model or
    # --hotkey given in the same command.
    if args.export_dictionary:
        from pathlib import Path

        from murmur.config import dictionary_payload

        out = Path(args.export_dictionary)
        try:
            out.write_text(
                json.dumps(dictionary_payload(cfg), indent=2) + "\n", encoding="utf-8"
            )
        except OSError as e:
            log.error("Could not write %s: %s", out, e)
            return 1
        print(
            f"Wrote {_n(len(cfg.vocabulary), 'word')} and "
            f"{_n(len(cfg.replacements), 'replacement')} to {out}"
        )
        print("On the other device: murmur --import-dictionary, or Import on the settings page.")
        return 0
    if args.import_dictionary:
        from pathlib import Path

        from murmur.config import extract_dictionary, merge_dictionary, save

        try:
            data = json.loads(Path(args.import_dictionary).read_text(encoding="utf-8"))
        except OSError as e:
            log.error("Could not read %s: %s", args.import_dictionary, e)
            return 1
        except ValueError:
            log.error("%s is not JSON. Export it from Murmur on the other device.", args.import_dictionary)
            return 1
        try:
            vocab, repl = extract_dictionary(data)
        except ValueError as e:
            log.error("%s", e)
            return 1
        words, pairs = merge_dictionary(cfg, vocab, repl)
        if words or pairs:
            save(cfg)
        print(
            f"Added {_n(words, 'word')} and {_n(pairs, 'replacement')} "
            f"(now {_n(len(cfg.vocabulary), 'word')}, "
            f"{_n(len(cfg.replacements), 'replacement')})."
        )
        from murmur.server import find_running_instance

        if (words or pairs) and find_running_instance():
            print(
                "Murmur is running right now, so restart it to pick these up "
                "(or use Import on its settings page instead)."
            )
        return 0

    if args.hotkey:
        cfg.hotkey = args.hotkey
    if args.hotkey2:
        cfg.hotkey2 = args.hotkey2
    if args.hotkey or args.hotkey2:
        from murmur.config import validate_hotkeys

        try:
            validate_hotkeys(cfg)
        except ValueError as e:
            log.error("%s", e)
            return 2
    if args.model:
        from murmur.models import check_model_name

        problem = check_model_name(args.model)
        if problem:
            log.error("%s", problem)
            return 2
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
    if args.check_update:
        from murmur import updates

        info = updates.check(force=True)
        if info["available"]:
            print(f"Murmur {info['latest']} is available (you have {info['current']}).")
            print(f"What changed: {info['changelog']}")
            print("Quit Murmur, then update with:")
            print("  uv tool install --reinstall "
                  "https://github.com/nkalodner/murmur/archive/refs/heads/main.zip")
        elif info["latest"]:
            print(f"Murmur {info['current']} is the latest version.")
        else:
            print("Could not reach GitHub to check. Try again when you are online.")
            return 1
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

    # One copy at a time. Two running instances type every dictation twice,
    # which is the classic "I ran murmur in another terminal" mixup.
    from murmur.singleton import InstanceLock

    lock = InstanceLock()
    if not lock.acquire():
        from murmur.server import find_running_instance

        # The port being busy is the fast signal, but it is not proof: any
        # other program could hold it. Ask the settings server who is there
        # before refusing, so an unrelated squatter never locks Murmur out of
        # starting at all.
        url = find_running_instance()
        if url:
            log.error("Murmur is already running, so this copy will not start.")
            log.error("Its settings page is %s (also in the tray menu).", url)
            log.error("Quit that copy first if you want to restart it.")
            return 0
        log.warning(
            "Port %s is in use by something else; starting anyway. If you end up "
            "with two copies typing everything twice, quit one from the tray.",
            lock.port,
        )

    try:
        app = App(cfg)
    except LookupError as e:
        log.error("%s", e)
        lock.close()
        return 2
    try:
        app.run(use_tray=not args.no_tray, open_settings=args.settings)
    except ValueError as e:  # bad hotkey name
        log.error("%s", e)
        lock.close()
        return 2
    lock.close()
    if app._used_pill:
        # tkinter ran the pill in a background thread; a normal interpreter
        # exit would then finalize Tcl from the main thread and abort with
        # "async handler deleted by the wrong thread". Our own shutdown is
        # already done, so exit hard and skip that finalization.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0
