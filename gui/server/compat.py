"""Cross-platform shims that let the skill scripts run unchanged on Windows.

Two upstream behaviours are POSIX-only:

* ``preexec_fn=subprocess_rlimits`` — ``subprocess`` raises ``ValueError`` for
  ``preexec_fn`` on Windows, so every ``exiftool``/``c2patool`` call would fail
  there. The callers catch the exception, which means the tools silently look
  broken instead of working.
* Child processes pop up a console window on Windows.

Both are fixed here by wrapping ``subprocess.run`` for this process only. The
skill scripts are imported afterwards and pick the wrapper up through the
module object they already hold.
"""

from __future__ import annotations

import os
import subprocess
import sys

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

_applied = False
_notes: list[str] = []


def _patch_subprocess() -> None:
    original_run = subprocess.run
    if getattr(original_run, "_watermarks_gui_patched", False):
        return

    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    def run(*args, **kwargs):
        # preexec_fn is a POSIX-only knob; the resource caps it applies simply
        # do not exist on Windows.
        kwargs.pop("preexec_fn", None)
        flags = kwargs.get("creationflags", 0)
        kwargs["creationflags"] = flags | no_window
        return original_run(*args, **kwargs)

    run._watermarks_gui_patched = True  # type: ignore[attr-defined]
    subprocess.run = run  # type: ignore[assignment]


def apply() -> list[str]:
    """Install the shims once. Returns human-readable notes for diagnostics."""
    global _applied
    if _applied:
        return list(_notes)
    _applied = True

    if IS_WINDOWS:
        _patch_subprocess()
        _notes.append("Windows: subprocess resource limits skipped (POSIX-only)")
        _notes.append("Windows: helper tools run without a console window")

    return list(_notes)


def notes() -> list[str]:
    return list(_notes)
