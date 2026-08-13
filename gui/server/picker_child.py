"""Native file/folder picker, run as a short-lived child process.

Tkinter dialogs must own the main thread, and on macOS they must own the *first*
thread of the process. Running the dialog in a throwaway child keeps the server
free of both constraints, and a crashing/missing Tk cannot take the app down.

Exit codes: 0 = selection printed as JSON, 3 = no GUI toolkit available.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return 3

    mode = sys.argv[1] if len(sys.argv) > 1 else "files"
    title = sys.argv[2] if len(sys.argv) > 2 else "Choose"

    try:
        root = tk.Tk()
    except Exception:
        return 3

    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    try:
        if mode == "folder":
            picked = filedialog.askdirectory(title=title)
            paths = [picked] if picked else []
        elif mode == "save":
            picked = filedialog.asksaveasfilename(title=title)
            paths = [picked] if picked else []
        else:
            paths = list(filedialog.askopenfilenames(title=title) or ())
    except Exception:
        paths = []
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    sys.stdout.write(json.dumps([p for p in paths if p]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
