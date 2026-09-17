#!/usr/bin/env python
"""Write traceable release metadata beside the standalone distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_EDITION = "测试版"


def release_date_stamp(today: Optional[date] = None) -> str:
    """安装包日期标签：月.日，不补零。例如 9.16。"""
    day = today if today is not None else date.today()
    return f"{int(day.month)}.{int(day.day)}"


def release_setup_base_filename(today: Optional[date] = None, edition: str = APP_EDITION) -> str:
    """官方安装包文件名（不含 .exe）：LCA_9.16测试版_Setup。"""
    return f"LCA_{release_date_stamp(today)}{edition}_Setup"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist")
    parser.add_argument("--print-release-date", action="store_true")
    parser.add_argument("--print-setup-basename", action="store_true")
    args = parser.parse_args()
    if args.print_release_date:
        print(release_date_stamp())
        return 0
    if args.print_setup_basename:
        print(release_setup_base_filename())
        return 0
    if not args.dist:
        parser.error("必须提供 --dist，或使用 --print-release-date / --print-setup-basename")
    dist = Path(args.dist).resolve()
    files = {}
    for relative in ("main.exe", "DirectML.dll", "onnxruntime/capi/onnxruntime.dll"):
        path = dist / relative
        if path.is_file():
            files[relative] = {"size": path.stat().st_size, "sha256": _sha256(path)}
    metadata = {
        "schema_version": 1,
        "edition": APP_EDITION,
        "git_commit": _git_commit(),
        "built_at": time.time(),
        "files": files,
    }
    output = dist / "build-metadata.json"
    output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"build_metadata={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
