"""Native file/folder dialogs, delegated to a child process."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CHILD = Path(__file__).resolve().parent / "picker_child.py"


def pick(mode: str = "files", title: str = "Choose a file") -> dict:
    """Open a native dialog. Returns {'available': bool, 'paths': [...]}"""
    if mode not in ("files", "folder", "save"):
        mode = "files"
    try:
        r = subprocess.run(
            [sys.executable, str(CHILD), mode, title],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as e:
        return {"available": False, "paths": [], "error": str(e)}

    if r.returncode == 3:
        return {
            "available": False,
            "paths": [],
            "error": "No native file dialog on this system (Tkinter missing).",
        }
    if r.returncode != 0:
        return {"available": False, "paths": [], "error": (r.stderr or "").strip()[:400]}

    try:
        paths = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        paths = []
    return {"available": True, "paths": [p for p in paths if p]}
