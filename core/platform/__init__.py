"""Platform detection and toolkit dispatch."""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.platform.base import BasePlatformToolkit


def detect_platform() -> str:
    """Return 'mac', 'win', or 'unknown' based on sys.platform."""
    if sys.platform == "darwin":
        return "mac"
    elif sys.platform == "win32":
        return "win"
    return "unknown"


PLATFORM = detect_platform()

_toolkit: "BasePlatformToolkit | None" = None


def get_toolkit() -> "BasePlatformToolkit":
    """Return the platform-appropriate toolkit singleton."""
    global _toolkit
    if _toolkit is not None:
        return _toolkit
    if PLATFORM == "mac":
        from core.platform.mac.tools import MacToolkit
        _toolkit = MacToolkit()
    elif PLATFORM == "win":
        from core.platform.win.tools import WinToolkit
        _toolkit = WinToolkit()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}. X-Agent runs on macOS and Windows.")
    return _toolkit
