#!/usr/bin/env python3
"""Strip AI/C2PA provenance marks from given files in place.

Designed to run as a pre-commit hook: the pre-commit framework invokes this
with the staged files as positional arguments. It wraps clean_file.py
--in-place as a subprocess per file — no cleaning logic is duplicated here,
this is purely a batch-over-staged-files wrapper.

Rewriting a file a developer just staged is a real behavior change, not a
lint-and-continue: following the standard pre-commit auto-fixer convention
(same as e.g. black / ruff --fix hooks), this exits 1 whenever it modified
at least one file, so the hook framework stops the commit and the developer
reviews the diff and re-stages. Exit 0 means every file was already clean.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import eprint

CLEAN_FILE_PY = Path(__file__).resolve().parent / "clean_file.py"


def _changed(result: dict) -> bool:
    stats = result.get("stats")
    if stats is not None:
        return bool(stats.get("removed_count") or stats.get("replaced_count"))
    return bool(result.get("actions"))


def _clean_one(path: Path) -> str:
    """Returns 'changed', 'unchanged', or 'skipped'."""
    proc = subprocess.run(
        [sys.executable, str(CLEAN_FILE_PY), str(path), "--in-place", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 2:
        # Unrecognized format or oversized input; clean_file.py already
        # explained why on stderr, this is a non-fatal skip for the hook.
        return "skipped"
    if not proc.stdout.strip():
        eprint(f"{path}: {proc.stderr.strip() or 'clean_file.py produced no output'}")
        return "skipped"
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        eprint(f"{path}: could not parse clean_file.py output")
        return "skipped"
    return "changed" if _changed(result) else "unchanged"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "paths", nargs="+", type=Path, help="Files to clean in place (e.g. staged files)"
    )
    args = p.parse_args()

    changed_paths: list[Path] = []
    for path in args.paths:
        if not path.is_file():
            eprint(f"not a file: {path}")
            continue
        status = _clean_one(path)
        if status == "changed":
            changed_paths.append(path)

    if not changed_paths:
        return 0

    eprint(f"watermarks-remover: cleaned {len(changed_paths)} file(s) in place:")
    for path in changed_paths:
        eprint(f"  {path}")
    eprint("Review the changes and re-stage before committing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
