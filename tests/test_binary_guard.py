"""Tests for the binary-input guard on the text-only tools."""

from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "remove-ai-marks" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import guard_binary, looks_binary  # noqa: E402

DOCX_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>Table 1 holds the results.</w:t></w:r></w:p></w:body>"
    "</w:document>"
)


def make_docx(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", DOCX_XML)
    return path


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


# --- looks_binary ----------------------------------------------------------

@pytest.mark.parametrize(
    "data,expected_fragment",
    [
        (b"PK\x03\x04rest", "ZIP"),
        (b"%PDF-1.7\n", "PDF"),
        (b"\x89PNG\r\n\x1a\nrest", "PNG"),
        (b"\xff\xd8\xff\xe0rest", "JPEG"),
        (b"\x7fELF\x02\x01", "ELF"),
        (b"SQLite format 3\x00", "SQLite"),
        (b"plain text\x00with a nul", "NUL"),
    ],
)
def test_flags_binary(data, expected_fragment):
    kind = looks_binary(data)
    assert kind is not None
    assert expected_fragment.lower() in kind.lower()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"Just some prose.\n",
        b"# Markdown\n\n- bullet\n",
        "Accented prose: naïve café résumé\n".encode("utf-8"),
        "Zero width​ and nbsp here\n".encode("utf-8"),
        b"Latin-1 bytes: caf\xe9 na\xefve\n",  # not UTF-8, still text
        b"a\tb\r\nc\x0cd\x1b[0m\n",  # tabs, CRLF, form feed, ANSI escape
    ],
)
def test_allows_text(data):
    assert looks_binary(data) is None


def test_compressed_bytes_are_flagged(tmp_path):
    data = make_docx(tmp_path / "x.docx").read_bytes()
    assert looks_binary(data) is not None


def test_guard_binary_can_be_overridden():
    guard_binary(b"PK\x03\x04", "x.docx", allow_binary=True)  # must not raise
    with pytest.raises(SystemExit) as exc:
        guard_binary(b"PK\x03\x04", "x.docx")
    assert exc.value.code == 2


# --- CLI behaviour ---------------------------------------------------------

def test_inspect_text_refuses_docx(tmp_path):
    docx = make_docx(tmp_path / "doc.docx")
    r = run("inspect_text.py", str(docx))
    assert r.returncode == 2
    assert "looks like" in r.stderr
    assert "inspect_file.py" in r.stderr
    assert "Suspicious:" not in r.stdout


def test_inspect_text_force_text_still_works(tmp_path):
    docx = make_docx(tmp_path / "doc.docx")
    r = run("inspect_text.py", str(docx), "--force-text")
    assert r.returncode in (0, 1)
    assert "Length:" in r.stdout


def test_clean_text_refuses_docx_and_writes_nothing(tmp_path):
    docx = make_docx(tmp_path / "doc.docx")
    before = docx.read_bytes()
    out = tmp_path / "doc.cleaned.docx"
    r = run("clean_text.py", str(docx), "-o", str(out))
    assert r.returncode == 2
    assert not out.exists()
    assert docx.read_bytes() == before


def test_clean_text_in_place_leaves_docx_intact(tmp_path):
    docx = make_docx(tmp_path / "doc.docx")
    before = docx.read_bytes()
    r = run("clean_text.py", str(docx), "--in-place")
    assert r.returncode == 2
    assert docx.read_bytes() == before
    assert not (tmp_path / "doc.docx.bak").exists()


def test_clean_file_still_routes_docx_to_container(tmp_path):
    docx = make_docx(tmp_path / "doc.docx")
    out = tmp_path / "out.docx"
    r = run("clean_file.py", str(docx), "-o", str(out), "--json")
    assert r.returncode == 0, r.stderr
    assert out.exists()
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None
        assert "word/document.xml" in zf.namelist()


def test_clean_file_refuses_unknown_binary(tmp_path):
    blob = tmp_path / "mystery.bin"
    blob.write_bytes(b"\x00\x01\x02\x03" * 64)
    out = tmp_path / "out.bin"
    r = run("clean_file.py", str(blob), "-o", str(out))
    assert r.returncode == 2
    assert not out.exists()


def test_text_files_are_unaffected(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("Hidden​mark here.\n", encoding="utf-8")
    out = tmp_path / "note.cleaned.txt"
    r = run("clean_text.py", str(src), "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert out.read_text(encoding="utf-8") == "Hiddenmark here.\n"


def test_stdin_binary_is_refused():
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", DOCX_XML)
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "inspect_text.py")],
        input=docx.getvalue(),
        capture_output=True,
        timeout=60,
    )
    assert r.returncode == 2
    assert b"looks like" in r.stderr
