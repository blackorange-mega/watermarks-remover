"""Tests for the pre-commit hook wrappers (check_staged.py / clean_staged.py)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "service" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_staged
import clean_staged


def _watermarked_text() -> str:
    return "Hello" + chr(0x200B) + "World!"


def test_check_staged_clean_file_exits_0(tmp_path, monkeypatch, capsys):
    f = tmp_path / "clean.txt"
    f.write_text("Nothing to see here.", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_staged.py", str(f)])
    assert check_staged.main() == 0


def test_check_staged_marked_file_exits_1(tmp_path, monkeypatch, capsys):
    f = tmp_path / "marked.txt"
    f.write_text(_watermarked_text(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_staged.py", str(f)])
    assert check_staged.main() == 1
    err = capsys.readouterr().err
    assert str(f) in err
    assert "layer-a" in err


def test_check_staged_multiple_files_one_marked(tmp_path, monkeypatch, capsys):
    clean = tmp_path / "clean.txt"
    clean.write_text("plain text", encoding="utf-8")
    marked = tmp_path / "marked.txt"
    marked.write_text(_watermarked_text(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["check_staged.py", str(clean), str(marked)])
    assert check_staged.main() == 1
    err = capsys.readouterr().err
    assert str(marked) in err
    assert str(clean) not in err


def test_check_staged_unknown_format_skipped(tmp_path, monkeypatch):
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00\x01\x02\xff\xfe no known magic bytes here")
    monkeypatch.setattr(sys, "argv", ["check_staged.py", str(f)])
    assert check_staged.main() == 0


def test_check_staged_missing_path_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_staged.py", str(tmp_path / "nope.txt")])
    assert check_staged.main() == 2


def test_clean_staged_marked_file_cleans_and_exits_1(tmp_path, monkeypatch, capsys):
    f = tmp_path / "marked.txt"
    f.write_text(_watermarked_text(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["clean_staged.py", str(f)])
    assert clean_staged.main() == 1
    assert f.read_text(encoding="utf-8") == "HelloWorld!"
    err = capsys.readouterr().err
    assert str(f) in err


def test_clean_staged_already_clean_file_exits_0_unchanged(tmp_path, monkeypatch):
    f = tmp_path / "clean.txt"
    original = "Nothing to see here."
    f.write_text(original, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["clean_staged.py", str(f)])
    assert clean_staged.main() == 0
    assert f.read_text(encoding="utf-8") == original


def test_clean_staged_unknown_format_skipped(tmp_path, monkeypatch):
    f = tmp_path / "data.bin"
    original = b"\x00\x01\x02\xff\xfe no known magic bytes here"
    f.write_bytes(original)
    monkeypatch.setattr(sys, "argv", ["clean_staged.py", str(f)])
    assert clean_staged.main() == 0
    assert f.read_bytes() == original


def test_pre_commit_hooks_manifest_defines_both_hooks():
    # No PyYAML in this project's stdlib-only test deps (requirements-dev.txt) —
    # check the manifest's shape textually rather than adding a parser dependency.
    text = (ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "id: watermarks-remover-check" in text
    assert "id: watermarks-remover-clean" in text
    assert text.count("entry: python3 service/scripts/") == 2
    assert text.count("language: system") == 2
