"""Adapter between the GUI and the remove-ai-marks skill scripts.

Everything runs in-process: the skill modules are plain stdlib Python, so
importing them avoids a subprocess (and its argument-quoting pitfalls) per
action, and lets the GUI reuse the exact same code paths the CLI uses.
"""

from __future__ import annotations

import html
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

from . import compat

compat.apply()

GUI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = GUI_DIR.parent


def _find_scripts_dir() -> Path:
    override = os.environ.get("WATERMARKS_SKILL_DIR")
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates += [
        REPO_ROOT / "skills" / "remove-ai-marks" / "scripts",
        GUI_DIR / "skills" / "remove-ai-marks" / "scripts",
    ]
    for c in candidates:
        if (c / "text_unicode.py").is_file():
            return c.resolve()
    raise RuntimeError(
        "Cannot find skills/remove-ai-marks/scripts. Put the gui/ folder inside "
        "the watermarks-remover checkout, or set WATERMARKS_SKILL_DIR."
    )


SCRIPTS_DIR = _find_scripts_dir()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import common  # noqa: E402
import container_meta  # noqa: E402
import image_meta  # noqa: E402
import rewrite_text as rewrite_mod  # noqa: E402
import text_unicode  # noqa: E402

MAX_INPUT_BYTES = common.MAX_INPUT_BYTES

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
CONTAINER_EXTS = {".svg", ".pdf", ".docx", ".odt", ".html", ".htm", ".md", ".markdown", ".mdx"}
TEXT_EXTS = {
    ".txt", ".text", ".css", ".js", ".py", ".rs", ".go",
    ".json", ".yaml", ".yml", ".toml", ".csv",
}

REWRITE_STRENGTHS = ("paraphrase", "humanize", "code", "backtranslate", "structural")
REWRITE_BACKENDS = ("print-prompt", "ollama", "openai-compatible")

# Compact names for the reveal view. Unicode's official names are too long to
# sit inline in a paragraph, and "U+200B" alone tells a non-expert nothing.
MARK_ABBREV = {
    0x200B: "ZWSP", 0x200C: "ZWNJ", 0x200D: "ZWJ", 0xFEFF: "BOM",
    0x2060: "WJ", 0x00AD: "SHY", 0x180E: "MVS", 0x061C: "ALM",
    0x200E: "LRM", 0x200F: "RLM", 0x202A: "LRE", 0x202B: "RLE",
    0x202C: "PDF", 0x202D: "LRO", 0x202E: "RLO", 0x2066: "LRI",
    0x2067: "RLI", 0x2068: "FSI", 0x2069: "PDI", 0x00A0: "NBSP",
    0x202F: "NNBSP", 0x2007: "FIGSP", 0x2009: "THINSP", 0x200A: "HAIRSP",
    0x2002: "ENSP", 0x2003: "EMSP", 0x3000: "IDSP", 0x205F: "MMSP",
}

KIND_HELP = {
    "strip": "Invisible character with no visual role — a classic carrier for hidden marks.",
    "bidi": "Bidirectional control character. Can reorder text invisibly.",
    "tag_chars": "Unicode tag character. Can encode whole hidden messages.",
    "variation_selector": "Variation selector. Invisible, and can carry payload bits.",
    "zwj_family": "Zero-width joiner family. Invisible glue between characters.",
    "space": "A look-alike space that is not a plain space.",
    "confusable": "A letter that looks Latin but is from another alphabet.",
    "other_cf": "Other invisible format character.",
}


# ---------------------------------------------------------------------------
# Reveal: turn text into segments so the UI can show what is actually in there
# ---------------------------------------------------------------------------

REVEAL_MAX_CHARS = 400_000


def _mark_kind(ch: str, *, aggressive: bool) -> str | None:
    cp = ord(ch)
    if text_unicode._is_strip_cp(cp):
        return text_unicode._strip_kind(cp)
    if cp in text_unicode.SPACE_HOMOGLYPHS:
        return "space"
    if aggressive and cp in text_unicode.LATIN_CONFUSABLES:
        return "confusable"
    if unicodedata.category(ch) == "Cf" and cp not in (0x00AD,):
        return "other_cf"
    return None


def _abbrev(cp: int) -> str:
    if cp in MARK_ABBREV:
        return MARK_ABBREV[cp]
    name = unicodedata.name(chr(cp), "")
    if name:
        initials = "".join(w[0] for w in name.split() if w)[:5]
        if len(initials) >= 2:
            return initials
    return f"U+{cp:04X}"


def reveal_segments(text: str, *, aggressive: bool = False) -> dict[str, Any]:
    """Split text into plain runs and mark runs for the reveal view."""
    truncated = len(text) > REVEAL_MAX_CHARS
    body = text[:REVEAL_MAX_CHARS]

    segments: list[dict[str, Any]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            segments.append({"t": "text", "v": "".join(buf)})
            buf.clear()

    for ch in body:
        kind = _mark_kind(ch, aggressive=aggressive)
        if kind is None:
            buf.append(ch)
            continue
        flush()
        cp = ord(ch)
        segments.append(
            {
                "t": "mark",
                "v": _abbrev(cp),
                "kind": kind,
                "cp": f"U+{cp:04X}",
                "label": text_unicode._char_label(ch),
                # A space homoglyph still occupies a slot in the sentence, so
                # keep its replacement visible behind the chip.
                "sub": text_unicode.SPACE_HOMOGLYPHS.get(cp, ""),
            }
        )
    flush()
    return {"segments": segments, "truncated": truncated}


# ---------------------------------------------------------------------------
# Text (Layer A)
# ---------------------------------------------------------------------------

def inspect_text(text: str, *, aggressive: bool = False) -> dict[str, Any]:
    report = text_unicode.inspect_text(text, aggressive=aggressive)
    data = report.to_dict()
    for hit in data["hits"]:
        hit["help"] = KIND_HELP.get(hit["kind"], "")
    data["reveal"] = reveal_segments(text, aggressive=aggressive)
    data["clean"] = report.suspicious_total == 0
    return data


def clean_text(
    text: str,
    *,
    nfkc: bool = False,
    aggressive_homoglyphs: bool = False,
    normalize_spaces: bool = True,
) -> dict[str, Any]:
    cleaned, stats = text_unicode.clean_text(
        text,
        nfkc=nfkc,
        aggressive_homoglyphs=aggressive_homoglyphs,
        normalize_spaces=normalize_spaces,
    )
    return {"text": cleaned, "stats": stats}


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in CONTAINER_EXTS:
        return "container"
    if ext in TEXT_EXTS:
        return "text"
    data = path.read_bytes()
    if image_meta.detect_format(data) in ("png", "jpeg"):
        return "image"
    if container_meta.detect_container_format(path, data) != "unknown":
        return "container"
    return "text"


def _guard_size(path: Path) -> None:
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise ValueError(
            f"File is larger than the {MAX_INPUT_BYTES // (1 << 20)} MiB safety limit "
            f"({size // (1 << 20)} MiB)."
        )


def _decode(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def _is_texty_container(fmt: str) -> bool:
    return fmt in ("markdown", "html")


# ---------------------------------------------------------------------------
# Office containers: the prose lives inside the zip, so neither inspect_file
# nor inspect_text sees it. inspect_text.py on a .docx scans deflate-compressed
# bytes and reports whatever random codepoints fall out — pure noise.
# ---------------------------------------------------------------------------

OFFICE_TEXT_PARTS = {
    "docx": re.compile(
        r"^word/(document|footnotes|endnotes|comments)\.xml$"
        r"|^word/(header|footer)\d*\.xml$"
    ),
    "odt": re.compile(r"^(content|styles)\.xml$"),
}

# Character data is everything between tags; markup itself is never touched.
_XML_CHARDATA = re.compile(r">([^<]*)<", re.DOTALL)


def is_office_container(fmt: str) -> bool:
    return fmt in OFFICE_TEXT_PARTS


def office_text(data: bytes, fmt: str) -> str:
    """The readable text inside a DOCX/ODT, for inspection and reveal."""
    pattern = OFFICE_TEXT_PARTS.get(fmt)
    if pattern is None:
        return ""
    chunks: list[str] = []
    budget = [0]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if not pattern.match(info.filename):
                    continue
                container_meta._check_zip_budget(info, budget)
                try:
                    xml = zf.read(info.filename).decode("utf-8")
                except (UnicodeDecodeError, KeyError):
                    continue
                for m in _XML_CHARDATA.finditer(xml):
                    chunk = m.group(1)
                    if chunk:
                        chunks.append(html.unescape(chunk))
    except (zipfile.BadZipFile, ValueError):
        return ""
    return "".join(chunks)


def scrub_office_text(
    data: bytes,
    fmt: str,
    *,
    nfkc: bool = False,
    aggressive_homoglyphs: bool = False,
    normalize_spaces: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    """Rewrite only the character data of a DOCX/ODT, leaving markup byte-exact."""
    pattern = OFFICE_TEXT_PARTS.get(fmt)
    if pattern is None:
        return data, {"removed_count": 0, "replaced_count": 0, "parts": []}

    totals: dict[str, Any] = {"removed_count": 0, "replaced_count": 0, "parts": []}
    out = io.BytesIO()
    budget = [0]

    try:
        _rezip(data, pattern, out, budget, totals, nfkc, aggressive_homoglyphs, normalize_spaces)
    except (zipfile.BadZipFile, ValueError) as e:
        # A container we cannot safely rewrite is left exactly as it was.
        totals["error"] = str(e)
        return data, totals
    return out.getvalue(), totals


def _rezip(
    data: bytes,
    pattern: re.Pattern[str],
    out: io.BytesIO,
    budget: list[int],
    totals: dict[str, Any],
    nfkc: bool,
    aggressive_homoglyphs: bool,
    normalize_spaces: bool,
) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            container_meta._check_zip_budget(info, budget)
            raw = zin.read(info.filename)
            if pattern.match(info.filename):
                try:
                    xml = raw.decode("utf-8")
                except UnicodeDecodeError:
                    xml = None
                if xml is not None:
                    removed = replaced = 0

                    def _sub(m: re.Match[str]) -> str:
                        nonlocal removed, replaced
                        chunk = m.group(1)
                        if not chunk:
                            return m.group(0)
                        cleaned, st = text_unicode.clean_text(
                            chunk,
                            nfkc=nfkc,
                            aggressive_homoglyphs=aggressive_homoglyphs,
                            normalize_spaces=normalize_spaces,
                        )
                        removed += st["removed_count"]
                        replaced += st["replaced_count"]
                        return f">{cleaned}<"

                    new_xml = _XML_CHARDATA.sub(_sub, xml)
                    if removed or replaced:
                        totals["removed_count"] += removed
                        totals["replaced_count"] += replaced
                        totals["parts"].append(info.filename)
                        raw = new_xml.encode("utf-8")

            copy = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            copy.compress_type = info.compress_type
            copy.external_attr = info.external_attr
            copy.internal_attr = info.internal_attr
            copy.create_system = info.create_system
            zout.writestr(copy, raw)


def inspect_file(
    path: Path,
    *,
    aggressive: bool = False,
    force_type: str = "auto",
    synthid: bool = False,
) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    _guard_size(path)

    kind = force_type if force_type != "auto" else classify(path)
    out: dict[str, Any] = {
        "kind": kind,
        "path": str(path),
        "name": path.name,
        "size": path.stat().st_size,
    }

    if kind == "text":
        text = _decode(path)
        report = inspect_text(text, aggressive=aggressive)
        out.update(
            {
                "format": "text",
                "text_report": report,
                "findings": [
                    f"{h['label']} x{h['count']}" for h in report["hits"]
                ],
                "has_c2pa": False,
                "has_ai_metadata": report["suspicious_total"] > 0,
                "clean": report["clean"],
            }
        )
        return out

    if kind == "image":
        synthid_dir = os.environ.get("REVERSE_SYNTHID_DIR") if synthid else None
        report = image_meta.inspect_image(path, synthid_dir=synthid_dir)
        data = report.to_dict()
        out.update(data)
        out["clean"] = not (data["has_c2pa"] or data["has_ai_metadata"])
        return out

    report = container_meta.inspect_container(path)
    data = report.to_dict()
    out.update(data)
    # inspect_container only looks at metadata. Surface the text body too:
    # for md/html because clean_container already scrubs it, and for Office
    # files because that is where their prose actually lives.
    fmt = data.get("format", "")
    if _is_texty_container(fmt):
        try:
            text = _decode(path)
        except OSError:
            text = ""
        if text:
            out["text_report"] = inspect_text(text, aggressive=aggressive)
            out["text_source"] = "file text"
    elif is_office_container(fmt):
        text = office_text(path.read_bytes(), fmt)
        if text:
            out["text_report"] = inspect_text(text, aggressive=aggressive)
            out["text_source"] = "document body"
    text_dirty = bool(out.get("text_report") and not out["text_report"]["clean"])
    out["clean"] = not (data["has_c2pa"] or data["has_ai_metadata"] or text_dirty)
    return out


def clean_file(
    path: Path,
    dest: Path,
    *,
    force_type: str = "auto",
    nfkc: bool = False,
    aggressive_homoglyphs: bool = False,
    keep_non_ai_metadata: bool = False,
    synthid: bool = False,
    scrub_document_text: bool = False,
    convert_nbsp: bool = False,
) -> dict[str, Any]:
    path = Path(path)
    dest = Path(dest)
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    _guard_size(path)

    kind = force_type if force_type != "auto" else classify(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if kind == "text":
        text = _decode(path)
        cleaned, stats = text_unicode.clean_text(
            text, nfkc=nfkc, aggressive_homoglyphs=aggressive_homoglyphs
        )
        common.safe_write_text(dest, cleaned)
        actions = []
        if stats["removed_count"]:
            actions.append(f"removed {stats['removed_count']} invisible characters")
        if stats["replaced_count"]:
            actions.append(f"replaced {stats['replaced_count']} look-alike characters")
        if nfkc and stats["replaced"].get("NFKC_normalize"):
            actions.append("applied NFKC normalisation")
        if not actions:
            actions.append("nothing to remove — copied as-is")
        return {
            "kind": "text",
            "input": str(path),
            "output": str(dest),
            "format": "text",
            "actions": actions,
            "stats": stats,
            "bytes_in": path.stat().st_size,
            "bytes_out": dest.stat().st_size,
            "still_has_c2pa": False,
            "still_has_ai_metadata": False,
            "residual": False,
        }

    if kind == "image":
        synthid_dir = os.environ.get("REVERSE_SYNTHID_DIR") if synthid else None
        result = image_meta.clean_image(
            path,
            dest,
            strip_all_metadata=not keep_non_ai_metadata,
            synthid_dir=synthid_dir,
        )
        result = {"kind": "image", **result}
        result["residual"] = bool(result["still_has_c2pa"] or result["still_has_ai_metadata"])
        if not result["actions"]:
            result["actions"] = ["no metadata segments found — re-encoded container"]
        return result

    result = container_meta.clean_container(path, dest)
    result = {"kind": "container", **result}

    if scrub_document_text and is_office_container(result.get("format", "")):
        scrubbed, totals = scrub_office_text(
            dest.read_bytes(),
            result["format"],
            nfkc=nfkc,
            aggressive_homoglyphs=aggressive_homoglyphs,
            normalize_spaces=convert_nbsp,
        )
        if totals["removed_count"] or totals["replaced_count"]:
            common.safe_write_bytes(dest, scrubbed)
            result["bytes_out"] = dest.stat().st_size
            result["actions"].append(
                f"document text: removed {totals['removed_count']}, "
                f"replaced {totals['replaced_count']} "
                f"in {', '.join(totals['parts'])}"
            )
        else:
            result["actions"].append("document text: nothing to remove")

    result["residual"] = bool(result["still_has_c2pa"] or result["still_has_ai_metadata"])
    if result.get("meta", {}).get("degraded"):
        result["degraded"] = True
    if not result["actions"]:
        result["actions"] = ["no metadata found — copied as-is"]
    return result


def backup_then_clean(path: Path, **kwargs: Any) -> dict[str, Any]:
    """In-place clean: keep the original as .bak, write the cleaned file over it."""
    path = Path(path)
    bak = common.backup_path(path)
    result = clean_file(bak, path, **kwargs)
    result["backup"] = str(bak)
    result["input"] = str(path)
    return result


def cleaned_path(path: Path) -> Path:
    return common.cleaned_path(Path(path))


# ---------------------------------------------------------------------------
# Layer B rewrite
# ---------------------------------------------------------------------------

def build_prompt(text: str, *, strength: str, lang: str, original_lang: str) -> str:
    return rewrite_mod.build_prompt(strength, text, lang=lang, original_lang=original_lang)


def rewrite(
    text: str,
    *,
    backend: str,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    strength: str,
    lang: str,
    original_lang: str,
    timeout: float,
    temperature: float,
    candidates: int,
    layer_a_after: bool,
    allow_remote: bool,
) -> dict[str, Any]:
    if backend not in REWRITE_BACKENDS:
        raise ValueError(f"Unknown backend: {backend}")
    if strength not in REWRITE_STRENGTHS:
        raise ValueError(f"Unknown strength: {strength}")

    out, info = rewrite_mod.rewrite(
        text,
        backend=backend,
        model=model or None,
        base_url=base_url or None,
        api_key=api_key or None,
        strength=strength,
        lang=lang,
        original_lang=original_lang,
        timeout=timeout,
        layer_a_after=layer_a_after,
        temperature=temperature,
        candidates=candidates,
        allow_remote=allow_remote,
    )
    divergence = None
    if info.get("mode") == "rewritten":
        divergence = rewrite_mod._lexical_divergence(text, out)
    return {"text": out, "info": info, "divergence": divergence}


def probe_endpoint(base_url: str, backend: str, timeout: float = 5.0) -> dict[str, Any]:
    """Cheap reachability check for the rewrite endpoint, used by the UI."""
    import json
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/")
    probe = f"{url}/api/tags" if backend == "ollama" else f"{url}/models"
    try:
        with urllib.request.urlopen(probe, timeout=timeout) as resp:
            raw = resp.read(1 << 20)
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code} from {probe}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    models: list[str] = []
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        if backend == "ollama":
            models = [m.get("name", "") for m in payload.get("models", [])]
        else:
            models = [m.get("id", "") for m in payload.get("data", [])]
    except Exception:
        pass
    return {"ok": True, "models": [m for m in models if m][:80]}


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _tool_version(name: str, args: list[str]) -> dict[str, Any]:
    exe = shutil.which(name)
    if not exe:
        return {"available": False, "path": None, "version": None}
    version = None
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=15)
        version = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        version = version[0][:120] if version else None
    except Exception:
        pass
    return {"available": True, "path": exe, "version": version}


def diagnostics() -> dict[str, Any]:
    tk_ok = True
    try:
        import tkinter  # noqa: F401
    except Exception:
        tk_ok = False

    synthid_dir = os.environ.get("REVERSE_SYNTHID_DIR")
    return {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "scripts_dir": str(SCRIPTS_DIR),
        "max_input_mib": MAX_INPUT_BYTES // (1 << 20),
        "compat_notes": compat.notes(),
        "native_dialogs": tk_ok,
        "tools": {
            "exiftool": _tool_version("exiftool", ["-ver"]),
            "c2patool": _tool_version("c2patool", ["--version"]),
        },
        "synthid": {
            "configured": bool(synthid_dir),
            "dir": synthid_dir,
            "exists": bool(synthid_dir and Path(synthid_dir).is_dir()),
        },
        "rewrite_env": {
            "backend": os.environ.get("WATERMARKS_REWRITE_BACKEND"),
            "model": os.environ.get("WATERMARKS_REWRITE_MODEL"),
            "base_url": os.environ.get("WATERMARKS_REWRITE_BASE_URL"),
            "api_key_set": bool(os.environ.get("WATERMARKS_REWRITE_API_KEY")),
            "allow_remote": os.environ.get("WATERMARKS_REWRITE_ALLOW_REMOTE", ""),
        },
    }


def reference_docs() -> list[dict[str, str]]:
    """The repo's own reference notes, so the GUI can show them offline."""
    refs = REPO_ROOT / "skills" / "remove-ai-marks" / "references"
    docs = []
    if refs.is_dir():
        for p in sorted(refs.glob("*.md")):
            docs.append({"id": p.stem, "title": p.stem.replace("-", " ").title()})
    return docs


def reference_body(doc_id: str) -> str:
    refs = (REPO_ROOT / "skills" / "remove-ai-marks" / "references").resolve()
    target = (refs / f"{doc_id}.md").resolve()
    if target.parent != refs or not target.is_file():
        raise ValueError("Unknown document")
    return target.read_text(encoding="utf-8", errors="replace")
