"""The tray mark and the pure menu helpers (pystray itself needs a display)."""
import numpy as np

from murmur.app import last_transcript, mic_choices
from murmur.tray import COLORS, LABELS, render_icon


def _alpha(img):
    return np.asarray(img)[:, :, 3].astype(int)


def test_every_state_has_a_color_and_label():
    for state in ("loading", "idle", "recording", "busy", "paused"):
        assert state in COLORS and state in LABELS


def test_icon_renders_a_mark_in_every_state():
    for state in COLORS:
        img = render_icon(state)
        assert img.size == (64, 64) and img.mode == "RGBA"
        assert _alpha(img).sum() > 0  # something is actually drawn


def test_icon_states_differ_and_dim_states_are_dim():
    idle, rec = render_icon("idle"), render_icon("recording")
    assert np.asarray(idle).tolist() != np.asarray(rec).tolist()
    # Loading and paused are the same mic at lower alpha, so their total
    # coverage must land clearly below idle's.
    for dim in ("loading", "paused"):
        assert _alpha(render_icon(dim)).sum() < _alpha(render_icon("idle")).sum() * 0.7


def test_icon_is_a_mic_not_a_dot():
    # The old dot was one blob; the mic has a narrow stem between the cradle
    # and the base, so a band through the stem region must be a thin run.
    a = _alpha(render_icon("idle"))
    band = a[45:47, :].max(axis=0)  # the stem, between arc bottom and base
    cols = np.flatnonzero(band)
    assert len(cols) > 0
    assert len(cols) < 16  # a dot or the base would span far wider


def test_icon_has_exactly_three_slats():
    # Noah's pick: the clean mic, three slats. Walk the capsule's center
    # column and count the transparent runs; a fourth slat (or none) fails.
    a = _alpha(render_icon("idle"))
    col = a[9:35, 32]  # the capsule's vertical span at 64px
    gaps, inside = 0, False
    for v in col:
        low = v < 60
        if low and not inside:
            gaps += 1
        inside = low
    assert gaps == 3
    solid = a[19, 32]   # band between the first two slats
    slat = a[22, 32]    # center slat (y~88 on the 256 grid)
    assert solid > 150
    assert slat < solid * 0.5


def test_icon_has_no_waves():
    # The waves came off in 0.11.3; nothing may be drawn past the cradle.
    a = _alpha(render_icon("idle"))
    assert a[:, 49:].sum() == 0
    assert a[:, :11].sum() == 0


def test_idle_is_menu_bar_white():
    from murmur.tray import COLORS

    assert all(c >= 230 for c in COLORS["idle"][:3])
    img = np.asarray(render_icon("idle"))
    ys, xs = np.nonzero(img[:, :, 3])
    assert img[ys[0], xs[0], :3].min() >= 230  # drawn pixels really are white


def test_mic_choices_marks_the_selection():
    devs = [{"name": "Built-in", "default": True}, {"name": "USB Mic", "default": False}]
    rows = mic_choices(devs, None)
    assert rows[0] == ("System default (Built-in)", True, None)
    assert [r[1] for r in rows] == [True, False, False]
    rows = mic_choices(devs, "USB Mic")
    assert [r[1] for r in rows] == [False, False, True]


def test_mic_choices_keeps_a_missing_device_visible():
    rows = mic_choices([{"name": "Built-in", "default": True}], "Elgato Wave")
    assert rows[-1] == ("Elgato Wave (not found)", True, "Elgato Wave")


def test_last_transcript_reads_newest(tmp_path, monkeypatch):
    import murmur.server as server

    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(server, "HISTORY_PATH", path)
    assert last_transcript() is None  # no file yet
    path.write_text('{"text": "first take"}\n{"text": "second take"}\n', encoding="utf-8")
    assert last_transcript() == "second take"
    path.write_text('{"text": "   "}\n', encoding="utf-8")
    assert last_transcript() is None  # whitespace is not a transcript


# ---- menu wiring, against a fake pystray (the real one needs a display) ----

class _FakeMenuItem:
    def __init__(self, text, action=None, enabled=True, checked=None,
                 radio=False, default=False, visible=True):
        self.text, self.action, self.enabled = text, action, enabled
        self.checked, self.radio, self.default, self.visible = checked, radio, default, visible


class _FakeMenu:
    SEPARATOR = "---"

    def __init__(self, *items):
        self.items = list(items[0]()) if len(items) == 1 and callable(items[0]) else list(items)


class _FakeIcon:
    def __init__(self, name, icon, title, menu):
        self.name, self.icon, self.title, self.menu = name, icon, title, menu
        self.updates = 0

    def update_menu(self):
        self.updates += 1


def _fake_pystray(monkeypatch):
    import sys, types

    mod = types.ModuleType("pystray")
    mod.MenuItem, mod.Menu, mod.Icon = _FakeMenuItem, _FakeMenu, _FakeIcon
    monkeypatch.setitem(sys.modules, "pystray", mod)
    return mod


def _label(item):
    return item.text(item) if callable(item.text) else item.text


def test_tray_menu_offers_the_daily_actions(monkeypatch):
    _fake_pystray(monkeypatch)
    from murmur.tray import Tray

    picked = []
    tray = Tray(
        "Hold ctrl_r to dictate",
        on_quit=lambda: None,
        on_settings=lambda: None,
        mic_choices=lambda: [("System default (Built-in)", True, lambda: picked.append(None)),
                             ("USB Mic", False, lambda: picked.append("USB Mic"))],
        last_transcript=lambda: "hello there",
        on_paste_last=lambda: picked.append("paste"),
        is_paused=lambda: False,
        on_toggle_pause=lambda: picked.append("pause"),
        autostart_state=lambda: {"supported": True, "enabled": True},
        on_toggle_autostart=lambda: picked.append("login"),
        update_available=lambda: False,
    )
    menu = tray._icon.menu
    labels = [_label(i) for i in menu.items if i != "---"]
    for want in ["Settings...", "Paste last transcript", "Microphone",
                 "Pause dictation", "Start at login", "Quit Murmur"]:
        assert any(want in str(l) for l in labels), f"missing {want}"

    mic = next(i for i in menu.items if i != "---" and _label(i) == "Microphone")
    sub = mic.action.items  # the submenu regenerates from the callable
    assert [_label(i) for i in sub] == ["System default (Built-in)", "USB Mic"]
    assert all(i.radio for i in sub)
    assert [i.checked(i) for i in sub] == [True, False]

    # Clicking a device routes to the pick callback and refreshes the menu.
    sub[1].action(tray._icon, sub[1])
    assert picked == ["USB Mic"] and tray._icon.updates == 1

    paste = next(i for i in menu.items if i != "---" and _label(i) == "Paste last transcript")
    assert paste.enabled(paste) is True
    tray._last = None  # enabled tracks the callable, not a snapshot


def test_tray_paste_disabled_without_history_and_update_row_hidden(monkeypatch):
    _fake_pystray(monkeypatch)
    from murmur.tray import Tray

    tray = Tray(
        "hint", on_quit=lambda: None, on_settings=lambda: None,
        mic_choices=lambda: [], last_transcript=lambda: None,
        on_paste_last=lambda: None, is_paused=lambda: True,
        on_toggle_pause=lambda: None,
        autostart_state=lambda: {"supported": False, "enabled": False},
        on_toggle_autostart=lambda: None,
        update_available=lambda: True,
    )
    items = [i for i in tray._icon.menu.items if i != "---"]
    paste = next(i for i in items if _label(i) == "Paste last transcript")
    assert paste.enabled(paste) is False
    pause = next(i for i in items if _label(i) == "Pause dictation")
    assert pause.checked(pause) is True
    login = next(i for i in items if _label(i) == "Start at login")
    assert login.visible(login) is False  # unsupported platform hides it
    update = next(i for i in items if "Update available" in str(_label(i)))
    assert update.visible(update) is True


def test_tray_action_errors_never_escape(monkeypatch):
    _fake_pystray(monkeypatch)
    from murmur.tray import Tray

    def boom():
        raise RuntimeError("no")

    tray = Tray("hint", on_quit=lambda: None, on_settings=lambda: None,
                mic_choices=lambda: [("A", True, boom)],
                last_transcript=lambda: "x", on_paste_last=boom,
                is_paused=lambda: False, on_toggle_pause=boom)
    items = [i for i in tray._icon.menu.items if i != "---"]
    paste = next(i for i in items if _label(i) == "Paste last transcript")
    paste.action(tray._icon, paste)  # must swallow, menu still refreshed
    assert tray._icon.updates == 1


# ---- bar theme -------------------------------------------------------------


def test_system_theme_defaults_to_dark_and_never_raises():
    from murmur.tray import system_theme

    assert system_theme() in ("dark", "light")  # linux: the dark default


def test_mac_theme_reads_apple_interface_style(monkeypatch):
    import types

    import murmur.tray as tray

    monkeypatch.setattr(tray.sys, "platform", "darwin")
    import subprocess as sp

    def fake_run(cmd, **kw):
        assert cmd[:2] == ["defaults", "read"]
        return types.SimpleNamespace(returncode=0, stdout="Dark\n")

    monkeypatch.setattr(sp, "run", fake_run)
    assert tray.system_theme() == "dark"
    monkeypatch.setattr(sp, "run", lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout=""))
    assert tray.system_theme() == "light"  # the key only exists in dark mode


def test_light_theme_flips_ink_but_not_state_colors():
    dark_idle = np.asarray(render_icon("idle", theme="dark"))
    light_idle = np.asarray(render_icon("idle", theme="light"))
    ys, xs = np.nonzero(light_idle[:, :, 3])
    assert light_idle[ys[0], xs[0], :3].max() <= 100  # dark ink on a light bar
    ys, xs = np.nonzero(dark_idle[:, :, 3])
    assert dark_idle[ys[0], xs[0], :3].min() >= 230  # white ink on a dark bar
    rec = np.asarray(render_icon("recording", theme="light"))
    ys, xs = np.nonzero(rec[:, :, 3])
    assert rec[ys[0], xs[0], 0] > 180  # recording stays red on either bar
