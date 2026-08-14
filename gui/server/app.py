"""Local HTTP server behind the GUI.

Loopback-only, and every /api/ call must carry the session token handed to the
page at launch. Without that, any web page open in the same browser could drive
a server that reads and writes files on this machine.
"""

from __future__ import annotations

import atexit
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import traceback
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import bridge, picker

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MAX_BODY = bridge.MAX_INPUT_BYTES + (1 << 20)

TOKEN = secrets.token_urlsafe(32)
WORKDIR = Path(tempfile.mkdtemp(prefix="watermarks-gui-"))

_files: dict[str, dict[str, Any]] = {}
_files_lock = threading.Lock()

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ \-()\[\]]+")

# Control characters have no business in a header value; a stray CR/LF would
# let a crafted name inject headers of its own.
_HEADER_JUNK = re.compile(r"[\x00-\x1f\x7f]")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def _asset_map() -> dict[str, Path]:
    """Every shipped file under ``web/``, keyed by its request path.

    Serving from a table built by walking the directory means a request never
    contributes to a filesystem path: an unknown key is a 404 and nothing else.
    """
    root = WEB_DIR.resolve()
    assets: dict[str, Path] = {}
    for entry in sorted(root.rglob("*")):
        if not entry.is_file():
            continue
        real = entry.resolve()
        if real.is_relative_to(root):  # skip a symlink pointing out of web/
            assets[entry.relative_to(root).as_posix()] = real
    return assets


ASSETS = _asset_map()


@atexit.register
def _cleanup() -> None:
    shutil.rmtree(WORKDIR, ignore_errors=True)


def _safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = _SAFE_NAME.sub("_", name).strip() or "file"
    return name[:120]


def register(path: Path, name: str | None = None, origin: str = "output") -> str:
    fid = secrets.token_urlsafe(12)
    with _files_lock:
        _files[fid] = {
            "path": str(Path(path).resolve()),
            "name": name or Path(path).name,
            "origin": origin,
        }
    return fid


def lookup(fid: str) -> dict[str, Any] | None:
    with _files_lock:
        entry = _files.get(fid)
    return dict(entry) if entry else None


def resolve_ref(ref: dict[str, Any]) -> tuple[Path, str, bool]:
    """Resolve a client file reference to (path, display name, is_local).

    ``is_local`` means the user picked a real file on disk (so we may offer to
    write next to it); uploads live in the throwaway work directory.
    """
    if not isinstance(ref, dict):
        raise ValueError("Missing file reference")
    fid = ref.get("id")
    if fid:
        entry = lookup(str(fid))
        if not entry:
            raise ValueError("That file is no longer available — add it again.")
        return Path(entry["path"]), entry["name"], entry["origin"] == "local"
    raw = ref.get("path")
    if raw:
        p = Path(str(raw)).expanduser()
        if not p.is_file():
            raise ValueError(f"Not a file: {p}")
        return p.resolve(), p.name, True
    raise ValueError("Missing file reference")


class Handler(BaseHTTPRequestHandler):
    server_version = "watermarks-remover-gui"
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:  # quiet by default
        if os.environ.get("WATERMARKS_GUI_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        headers = {
            "Content-Type": ctype,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
                "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'"
            ),
            **(extra or {}),
        }
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, _HEADER_JUNK.sub("", str(v)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _fail(self, message: str, code: int = 400) -> None:
        self._json({"error": message}, code)

    def _reject(self, message: str) -> None:
        """Refuse without reading the body, so drop the connection with it.

        Leaving an unread body on a keep-alive connection makes the next
        request line start mid-payload; closing is both correct and keeps an
        unauthorized caller from parking megabytes in memory.
        """
        self.close_connection = True
        self._json({"error": message}, 403)

    def _guard(self) -> bool:
        """Loopback host + session token. Blocks other local apps and web pages."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("127.0.0.1", "localhost", "::1"):
            self._reject("Bad host")
            return False
        origin = self.headers.get("Origin")
        if origin:
            o = urlparse(origin)
            if o.hostname not in ("127.0.0.1", "localhost", "::1"):
                self._reject("Bad origin")
                return False
        token = self.headers.get("X-WM-Token") or ""
        if not secrets.compare_digest(token, TOKEN):
            self._reject("Bad session token — reopen the app window.")
            return False
        return True

    def _read_body(self) -> None:
        """Consume the request body exactly once, before any handler runs."""
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            raise ValueError("Request too large")
        self._raw = self.rfile.read(length) if length else b""

    def _payload(self) -> dict[str, Any]:
        raw = getattr(self, "_raw", b"")
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"Bad JSON body: {e}") from e
        return data if isinstance(data, dict) else {}

    # -- routing ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        try:
            if route in ("/", "/index.html"):
                return self._static("index.html")
            if route.startswith("/assets/"):
                return self._static(route[len("/assets/"):])
            if route == "/api/download":
                if not self._guard():
                    return
                return self._download(parse_qs(parsed.query))
            if route == "/api/download-all":
                if not self._guard():
                    return
                return self._download_all(parse_qs(parsed.query))
            self._fail("Not found", 404)
        except Exception as e:
            self._unexpected(e)

    do_HEAD = do_GET

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if not route.startswith("/api/"):
            return self._fail("Not found", 404)
        if not self._guard():
            return
        try:
            self._read_body()
            handler = ROUTES.get(route)
            if handler is None:
                return self._fail("Not found", 404)
            handler(self)
        except ValueError as e:
            self._fail(str(e), 400)
        except SystemExit as e:  # the skill scripts raise this for bad config
            self._fail(str(e) or "Operation refused", 400)
        except Exception as e:
            self._unexpected(e)

    def _unexpected(self, exc: Exception) -> None:
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        try:
            self._json({"error": detail}, 500)
        except Exception:
            pass

    # -- static -----------------------------------------------------------
    def _static(self, rel: str) -> None:
        target = ASSETS.get(unquote(rel))
        if target is None or not target.is_file():
            return self._fail("Not found", 404)
        ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # -- downloads --------------------------------------------------------
    def _download(self, query: dict[str, list[str]]) -> None:
        fid = (query.get("id") or [""])[0]
        entry = lookup(fid)
        if not entry or not Path(entry["path"]).is_file():
            return self._fail("File not found", 404)
        data = Path(entry["path"]).read_bytes()
        name = _safe_name(entry["name"])
        self._send(
            200,
            data,
            "application/octet-stream",
            {"Content-Disposition": f'attachment; filename="{name}"'},
        )

    def _download_all(self, query: dict[str, list[str]]) -> None:
        ids = [i for i in (query.get("ids") or [""])[0].split(",") if i]
        entries = [e for e in (lookup(i) for i in ids) if e and Path(e["path"]).is_file()]
        if not entries:
            return self._fail("Nothing to download", 404)
        buf = io.BytesIO()
        used: set[str] = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in entries:
                name = _safe_name(entry["name"])
                stem, dot, ext = name.partition(".")
                n = 1
                while name in used:
                    n += 1
                    name = f"{stem}-{n}{dot}{ext}"
                used.add(name)
                zf.write(entry["path"], arcname=name)
        self._send(
            200,
            buf.getvalue(),
            "application/zip",
            {"Content-Disposition": 'attachment; filename="cleaned-files.zip"'},
        )


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------

def api_diagnostics(h: Handler) -> None:
    h._json(bridge.diagnostics())


def api_refs(h: Handler) -> None:
    data = h._payload()
    doc_id = data.get("id")
    if doc_id:
        h._json({"id": doc_id, "body": bridge.reference_body(str(doc_id))})
        return
    h._json({"docs": bridge.reference_docs()})


def api_pick(h: Handler) -> None:
    data = h._payload()
    result = picker.pick(str(data.get("mode") or "files"), str(data.get("title") or "Choose a file"))
    out = []
    for raw in result.get("paths", []):
        p = Path(raw)
        if not p.is_file() and str(data.get("mode")) != "folder":
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append(
            {
                "id": register(p, p.name, origin="local"),
                "name": p.name,
                "path": str(p),
                "size": size,
                "local": True,
            }
        )
    h._json({"available": result.get("available", False), "error": result.get("error"), "files": out})


def api_upload(h: Handler) -> None:
    # The browser percent-encodes the name: HTTP headers cannot carry raw UTF-8.
    name = _safe_name(unquote(h.headers.get("X-WM-Filename") or "dropped-file"))
    raw = h._raw
    if len(raw) > bridge.MAX_INPUT_BYTES:
        raise ValueError(
            f"File is larger than the {bridge.MAX_INPUT_BYTES // (1 << 20)} MiB safety limit."
        )
    folder = WORKDIR / secrets.token_urlsafe(8)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_bytes(raw)
    h._json(
        {
            "id": register(target, name, origin="upload"),
            "name": name,
            "size": len(raw),
            "local": False,
        }
    )


def api_inspect(h: Handler) -> None:
    data = h._payload()
    path, name, is_local = resolve_ref(data.get("file") or {})
    report = bridge.inspect_file(
        path,
        aggressive=bool(data.get("aggressive")),
        force_type=str(data.get("as") or "auto"),
        synthid=bool(data.get("synthid")),
    )
    report["name"] = name
    report["local"] = is_local
    report["display_path"] = str(path) if is_local else name
    h._json(report)


def api_clean(h: Handler) -> None:
    data = h._payload()
    path, name, is_local = resolve_ref(data.get("file") or {})
    save = str(data.get("save") or "copy")
    opts = {
        "force_type": str(data.get("as") or "auto"),
        "nfkc": bool(data.get("nfkc")),
        "aggressive_homoglyphs": bool(data.get("aggressive_homoglyphs")),
        "keep_non_ai_metadata": bool(data.get("keep_non_ai_metadata")),
        "synthid": bool(data.get("synthid")),
        "scrub_document_text": bool(data.get("scrub_document_text")),
        "convert_nbsp": bool(data.get("convert_nbsp")),
    }

    if save == "inplace":
        if not is_local:
            raise ValueError("Overwriting only works for files opened with Browse.")
        result = bridge.backup_then_clean(path, **opts)
        out_path = path
    else:
        if is_local and save == "copy":
            out_path = bridge.cleaned_path(path)
        else:
            folder = WORKDIR / secrets.token_urlsafe(8)
            folder.mkdir(parents=True, exist_ok=True)
            out_path = folder / bridge.cleaned_path(Path(name)).name
        result = bridge.clean_file(path, out_path, **opts)

    result["download_id"] = register(out_path, Path(out_path).name, origin="output")
    result["output_name"] = Path(out_path).name
    result["saved_to_disk"] = is_local and save in ("copy", "inplace")
    result["name"] = name
    h._json(result)


def api_text_inspect(h: Handler) -> None:
    data = h._payload()
    text = str(data.get("text") or "")
    h._json(bridge.inspect_text(text, aggressive=bool(data.get("aggressive"))))


def api_text_clean(h: Handler) -> None:
    data = h._payload()
    text = str(data.get("text") or "")
    result = bridge.clean_text(
        text,
        nfkc=bool(data.get("nfkc")),
        aggressive_homoglyphs=bool(data.get("aggressive_homoglyphs")),
    )
    result["report"] = bridge.inspect_text(result["text"], aggressive=bool(data.get("aggressive")))
    h._json(result)


def api_text_save(h: Handler) -> None:
    data = h._payload()
    text = str(data.get("text") or "")
    name = _safe_name(str(data.get("name") or "cleaned.txt"))
    folder = WORKDIR / secrets.token_urlsafe(8)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_text(text, encoding="utf-8")
    h._json({"download_id": register(target, name, origin="output"), "name": name})


def api_rewrite_prompt(h: Handler) -> None:
    data = h._payload()
    prompt = bridge.build_prompt(
        str(data.get("text") or ""),
        strength=str(data.get("strength") or "paraphrase"),
        lang=str(data.get("lang") or "French"),
        original_lang=str(data.get("original_lang") or "English"),
    )
    h._json({"prompt": prompt})


def api_rewrite(h: Handler) -> None:
    data = h._payload()
    result = bridge.rewrite(
        str(data.get("text") or ""),
        backend=str(data.get("backend") or "print-prompt"),
        model=str(data.get("model") or "") or None,
        base_url=str(data.get("base_url") or "") or None,
        api_key=str(data.get("api_key") or "") or None,
        strength=str(data.get("strength") or "paraphrase"),
        lang=str(data.get("lang") or "French"),
        original_lang=str(data.get("original_lang") or "English"),
        timeout=float(data.get("timeout") or 120.0),
        temperature=float(data.get("temperature") or 0.9),
        candidates=int(data.get("candidates") or 1),
        layer_a_after=bool(data.get("layer_a_after", True)),
        allow_remote=bool(data.get("allow_remote")),
    )
    h._json(result)


def api_rewrite_probe(h: Handler) -> None:
    data = h._payload()
    h._json(
        bridge.probe_endpoint(
            str(data.get("base_url") or "http://127.0.0.1:11434"),
            str(data.get("backend") or "ollama"),
        )
    )


def api_shutdown(h: Handler) -> None:
    h._json({"ok": True})
    threading.Thread(target=h.server.shutdown, daemon=True).start()


ROUTES = {
    "/api/diagnostics": api_diagnostics,
    "/api/refs": api_refs,
    "/api/pick": api_pick,
    "/api/upload": api_upload,
    "/api/inspect": api_inspect,
    "/api/clean": api_clean,
    "/api/text/inspect": api_text_inspect,
    "/api/text/clean": api_text_clean,
    "/api/text/save": api_text_save,
    "/api/rewrite": api_rewrite,
    "/api/rewrite/prompt": api_rewrite_prompt,
    "/api/rewrite/probe": api_rewrite_probe,
    "/api/shutdown": api_shutdown,
}


def make_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.allow_reuse_address = False
    return ThreadingHTTPServer((host, port), Handler)
