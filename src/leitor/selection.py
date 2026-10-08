"""Read the X11 PRIMARY selection (whatever text is selected right now)."""

import shutil
import subprocess


def read_primary_selection() -> str:
    """Text currently selected in any X11 application."""
    if shutil.which("xclip") is None:
        return ""
    try:
        out = subprocess.run(
            ["xclip", "-o", "-selection", "primary"],
            capture_output=True, timeout=2, check=False,
        )
    except subprocess.TimeoutExpired:
        return ""
    return out.stdout.decode("utf-8", errors="replace")
