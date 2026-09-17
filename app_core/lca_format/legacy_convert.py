"""把旧工程转换成现行 LCA 包：外层 zip，只加密脚本，YOLO 等资源不加密。

现行打开路径只认转换后的格式。本模块读取：
- 旧 JSON 工作流
- 旧整包加密 LCA1
- 中间明文 zip 工程
并写成现行包。
"""

from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Mapping, Optional

from app_core.lca_format.constants import (
    ENTRY_WORKFLOW,
    LCA_EXTENSION,
    LCA_MAGIC,
    SCRIPTS_PAYLOAD_NAME,
    USER_ERROR_CONVERT,
    USER_ERROR_INVALID,
)
from app_core.lca_format.container import (
    ZIP_MAGIC,
    LcaFormatError,
    _unseal_lca1_blob,
    _zip_bytes_to_files,
    seal_lca_bytes,
    unseal_lca_bytes,
)
from task_workflow.workflow_sanitize import sanitize_workflow_data

KIND_CURRENT = "current"
KIND_LEGACY_LCA1 = "legacy_lca1"
KIND_PLAIN_ZIP = "plain_zip"
KIND_JSON = "json"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=4).encode("utf-8")


def _is_workflow_payload(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("cards"), list):
        return True
    nested = data.get("workflow")
    return isinstance(nested, dict) and isinstance(nested.get("cards"), list)


def _parse_json_bytes(blob: bytes) -> Optional[dict]:
    text = blob.decode("utf-8-sig")
    payload = json.loads(text)
    if _is_workflow_payload(payload):
        return payload
    return None


def _zip_member_names(blob: bytes) -> Optional[set[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(blob), "r") as archive:
            names = set()
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = str(member.filename or "").replace("\\", "/").lstrip("/")
                if name:
                    names.add(name)
            return names
    except zipfile.BadZipFile:
        return None


def inspect_project_bytes(blob: bytes) -> str:
    if blob.startswith(LCA_MAGIC):
        return KIND_LEGACY_LCA1
    if blob.startswith(ZIP_MAGIC):
        names = _zip_member_names(blob)
        if names is None:
            raise LcaFormatError(USER_ERROR_CONVERT)
        if SCRIPTS_PAYLOAD_NAME in names and "manifest.json" in names:
            return KIND_CURRENT
        if "manifest.json" in names or ENTRY_WORKFLOW in names:
            return KIND_PLAIN_ZIP
        raise LcaFormatError(USER_ERROR_CONVERT)
    try:
        if _parse_json_bytes(blob) is not None:
            return KIND_JSON
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    raise LcaFormatError(USER_ERROR_CONVERT)


def _manifest_bytes(display_name: str) -> bytes:
    from datetime import datetime, timezone

    return _json_bytes(
        {
            "schema_version": 2,
            "format": "lca_editor",
            "name": str(display_name or "工作流"),
            "entry_workflow": ENTRY_WORKFLOW,
            "scripts_payload": SCRIPTS_PAYLOAD_NAME,
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "files": [{"path": ENTRY_WORKFLOW, "role": "entry"}],
        }
    )


def convert_json_payload(payload: Mapping[str, object], *, display_name: str = "") -> bytes:
    cleaned = sanitize_workflow_data(copy.deepcopy(dict(payload)))
    files = {
        ENTRY_WORKFLOW: _json_bytes(cleaned),
        "manifest.json": _manifest_bytes(display_name),
    }
    return seal_lca_bytes(files)


def _convert_nested_members(files: Mapping[str, bytes]) -> Dict[str, bytes]:
    converted: Dict[str, bytes] = {}
    for path, data in files.items():
        if _normalize_is_lca(path):
            converted[path] = convert_project_bytes(data)
        else:
            converted[path] = data
    return converted


def _normalize_is_lca(path: object) -> bool:
    return _normalize_member(path).lower().endswith(LCA_EXTENSION)


def _normalize_member(path: object) -> str:
    return str(path or "").replace("\\", "/").lstrip("/")


def convert_project_bytes(blob: bytes, *, display_name: str = "") -> bytes:
    kind = inspect_project_bytes(blob)
    if kind == KIND_CURRENT:
        files = unseal_lca_bytes(blob)
        from app_core.lca_format.project_io import inline_nested_workflow_assets

        inlined = inline_nested_workflow_assets(files)
        if inlined is files:
            return blob
        return seal_lca_bytes(inlined)
    if kind == KIND_LEGACY_LCA1:
        files = _unseal_lca1_blob(blob)
        return seal_lca_bytes(_convert_nested_members(files))
    if kind == KIND_PLAIN_ZIP:
        files = _zip_bytes_to_files(blob)
        return seal_lca_bytes(_convert_nested_members(files))
    payload = _parse_json_bytes(blob)
    if payload is None:
        raise LcaFormatError(USER_ERROR_CONVERT)
    return convert_json_payload(payload, display_name=display_name)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def convert_project_file(path: str | Path) -> Path:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"工作流文件不存在: {source}")
    blob = source.read_bytes()
    converted = convert_project_bytes(blob, display_name=source.stem)
    if converted == blob:
        return source
    suffix = source.suffix.lower()
    if suffix == LCA_EXTENSION:
        _write_bytes(source, converted)
        return source
    if suffix == ".json":
        destination = source.with_suffix(LCA_EXTENSION)
        _write_bytes(destination, converted)
        try:
            if source.resolve() != destination.resolve():
                source.unlink()
        except OSError:
            pass
        return destination
    raise LcaFormatError(USER_ERROR_INVALID)
