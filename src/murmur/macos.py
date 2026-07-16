"""macOS permission preflight. Best effort; a failure here only means fewer helpful warnings."""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("murmur")

ACCESSIBILITY_HINT = (
    "Accessibility permission is missing, so pasting text will not work.\n"
    "  Fix: System Settings > Privacy & Security > Accessibility > enable your terminal app.\n"
    "  Shortcut: open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'"
)
INPUT_MONITORING_HINT = (
    "Input Monitoring permission is missing, so the hotkey will not be detected.\n"
    "  Fix: System Settings > Privacy & Security > Input Monitoring > enable your terminal app.\n"
    "  Shortcut: open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent'"
)


def preflight() -> list[str]:
    """Check Accessibility + Input Monitoring; trigger the Input Monitoring prompt if missing."""
    if sys.platform != "darwin":
        return []
    problems: list[str] = []
    import ctypes

    try:
        appsvc = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        appsvc.AXIsProcessTrusted.restype = ctypes.c_bool
        if not appsvc.AXIsProcessTrusted():
            problems.append(ACCESSIBILITY_HINT)
    except Exception as e:
        log.debug("accessibility preflight failed: %s", e)

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
