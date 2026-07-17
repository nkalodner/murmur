"""macOS permission preflight. Best effort; a failure here only means fewer helpful warnings."""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("murmur")

ACCESSIBILITY_HINT = (
    "Accessibility permission is missing, so pasting text will not work.\n"
    "  Fix: System Settings > Privacy & Security > Accessibility > turn on the entry running Murmur"
    ' (your terminal app, or "Python" when Murmur starts at login).\n'
    "  Shortcut: open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'"
)
INPUT_MONITORING_HINT = (
    "Input Monitoring permission is missing, so the hotkey will not be detected.\n"
    "  Fix: System Settings > Privacy & Security > Input Monitoring > turn on the entry running Murmur"
    ' (your terminal app, or "Python" when Murmur starts at login).\n'
    "  Shortcut: open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent'"
)


def preflight() -> list[str]:
    """Check Accessibility + Input Monitoring; prompt for each if missing.

    Both prompts add Murmur to the relevant Privacy list so the user only has
    to flip a toggle, instead of hunting down the hidden Python binary by hand.
    The grants persist once given (macOS keys them to the program), so this is a
    one-time step per install, not a per-launch chore.
    """
    if sys.platform != "darwin":
        return []
    problems: list[str] = []
    import ctypes

    # Accessibility: the prompting check (AXIsProcessTrustedWithOptions) adds
    # Murmur to the list and shows the dialog; the passive AXIsProcessTrusted
    # leaves nothing to toggle. pyobjc ships on the macOS build via pynput; fall
    # back to the passive ctypes check if it is somehow unavailable.
    trusted: bool | None = None
    try:
        import HIServices

        prompt_key = getattr(
            HIServices, "kAXTrustedCheckOptionPrompt", "AXTrustedCheckOptionPrompt"
        )
        trusted = bool(HIServices.AXIsProcessTrustedWithOptions({prompt_key: True}))
    except Exception as e:
        log.debug("accessibility prompt unavailable (%s); using passive check", e)
        try:
            appsvc = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
            )
            appsvc.AXIsProcessTrusted.restype = ctypes.c_bool
            trusted = bool(appsvc.AXIsProcessTrusted())
        except Exception as e2:
            log.debug("accessibility preflight failed: %s", e2)
    if trusted is False:
        problems.append(ACCESSIBILITY_HINT)

    try:
        cg = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGPreflightListenEventAccess.restype = ctypes.c_bool
        if not cg.CGPreflightListenEventAccess():
            cg.CGRequestListenEventAccess.restype = ctypes.c_bool
            cg.CGRequestListenEventAccess()  # pops the system permission dialog
            problems.append(INPUT_MONITORING_HINT)
    except Exception as e:
        log.debug("input monitoring preflight failed: %s", e)
    return problems
