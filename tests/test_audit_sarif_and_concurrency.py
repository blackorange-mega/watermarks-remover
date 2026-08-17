"""Tests for multi-worker concurrency and SARIF 2.1.0 export in audit_dir."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "service" / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from audit_lib import format_sarif

from tests.test_clean_image import _minimal_png_with_text


def test_format_sarif_structure():
    fake_report = {
        "root": "/workspace/project",
        "files_scanned": 3,
        "files": [
            {
                "path": "/workspace/project/assets/logo.png",
                "kind": "png",
                "has_c2pa": True,
                "has_ai_metadata": True,
                "findings": ["marker:C2PA manifest", "ai:Midjourney"],
                "confidence": ["confirmed", "probable"],
            },
            {
                "path": "/workspace/project/docs/readme.md",
                "kind": "markdown",
                "has_c2pa": False,
                "has_ai_metadata": False,
                "findings": ["layer-a: U+200B ZERO WIDTH SPACE x3 (zero_width)"],
                "confidence": ["probable"],
            },
            {
                "path": "/workspace/project/clean.txt",
                "kind": "text",
                "has_c2pa": False,
                "has_ai_metadata": False,
                "findings": [],
                "confidence": [],
            },
        ],
    }

    sarif = format_sarif(fake_report)
    assert sarif["version"] == "2.1.0"
    assert "$schema" in sarif
    assert len(sarif["runs"]) == 1

    run = sarif["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "watermarks-remover"
    rule_ids = {r["id"] for r in driver["rules"]}
    assert "AI-WATERMARK-C2PA" in rule_ids
    assert "AI-WATERMARK-METADATA" in rule_ids
    assert "AI-WATERMARK-UNICODE-LAYER-A" in rule_ids

    results = run["results"]
    assert len(results) == 3

    # Check first result (C2PA)
    c2pa_res = next(r for r in results if r["ruleId"] == "AI-WATERMARK-C2PA")
    assert c2pa_res["level"] == "error"
    assert "logo.png" in c2pa_res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]

    # Check Layer A result
    unicode_res = next(r for r in results if r["ruleId"] == "AI-WATERMARK-UNICODE-LAYER-A")
    assert unicode_res["level"] == "warning"
    assert "readme.md" in unicode_res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]


def test_audit_dir_serial_vs_parallel(tmp_path):
    # Setup multiple files
    for i in range(10):
        (tmp_path / f"text_{i}.txt").write_text(
            f"Text line {i} with \u200b carrier", encoding="utf-8"
        )
    (tmp_path / "image.png").write_bytes(_minimal_png_with_text())
    (tmp_path / "clean.md").write_text("# Pure human markdown", encoding="utf-8")

    # Run serial (-j 1)
    res_serial = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_dir.py"), str(tmp_path), "-j", "1", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_serial.returncode == 1
    data_serial = json.loads(res_serial.stdout)

    # Run parallel (-j 4)
    res_parallel = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_dir.py"), str(tmp_path), "-j", "4", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_parallel.returncode == 1
    data_parallel = json.loads(res_parallel.stdout)

    # Assert identical results
    assert data_serial["files_scanned"] == data_parallel["files_scanned"] == 12
    assert data_serial["summary"] == data_parallel["summary"]
    assert [f["path"] for f in data_serial["files"]] == [f["path"] for f in data_parallel["files"]]


def test_audit_dir_cli_sarif_output(tmp_path):
    (tmp_path / "prompt.txt").write_text("Hello\u200bWorld", encoding="utf-8")
    (tmp_path / "pic.png").write_bytes(_minimal_png_with_text())

    # Test --sarif flag
    res = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_dir.py"), str(tmp_path), "--sarif"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 1
    sarif_doc = json.loads(res.stdout)
    assert sarif_doc["version"] == "2.1.0"
    assert len(sarif_doc["runs"][0]["results"]) >= 2

    # Test --format sarif flag
    res2 = subprocess.run(
        [sys.executable, str(SCRIPTS / "audit_dir.py"), str(tmp_path), "--format", "sarif"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res2.returncode == 1
    sarif_doc2 = json.loads(res2.stdout)
    assert sarif_doc2["version"] == "2.1.0"
