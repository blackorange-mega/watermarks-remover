#!/usr/bin/env python3
"""Start the watermarks-remover GUI.

    python3 gui/launch.py

Opens a local, loopback-only app in a native window when pywebview is
installed, otherwise in your default browser. Nothing is uploaded anywhere:
the server only listens on 127.0.0.1 and every file stays on this machine.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.version_info < (3, 10):
    raise SystemExit(
        f"Python 3.10 or newer is required (found {sys.version.split()[0]}).\n"
        "Install it from https://www.python.org/downloads/ and try again."
    )

from server.app import TOKEN, make_server  # noqa: E402

BANNER = r"""
  watermarks-remover
  ------------------------------------------------
  Strip AI provenance marks from content you own.
"""


def _try_window(url: str, httpd) -> bool:
    """Native window via pywebview, if the user happens to have it."""
    try:
        import webview  # type: ignore
    except Exception:
        return False

    def _closed() -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    try:
        window = webview.create_window(
            "watermarks-remover",
            url,
            width=1180,
            height=820,
            min_size=(880, 620),
        )
        try:
            window.events.closed += _closed
        except AttributeError:  # pywebview < 4
            pass
        webview.start()
        return True
    except Exception as e:
        # No GUI backend (headless Linux, missing WebView2, old pywebview) —
        # the browser path below still works.
        print(f"  Native window unavailable ({e}); falling back to the browser.")
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=0, help="Fixed port (default: pick a free one)")
    p.add_argument("--no-browser", action="store_true", help="Do not open anything; print the URL")
    p.add_argument("--browser", action="store_true", help="Force the browser instead of a window")
    args = p.parse_args()

    httpd = make_server(port=args.port)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/?t={TOKEN}"

    print(BANNER)
    print(f"  Running at {url}")
    print("  Press Ctrl+C to stop.\n")

    if args.no_browser:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")
        finally:
            httpd.server_close()
        return 0

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        if args.browser or not _try_window(url, httpd):
            webbrowser.open(url)
            # The browser owns the UI now, so hold the process here.
            while thread.is_alive():
                thread.join(0.5)
    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
