from __future__ import annotations

import io
import json
import struct
import zipfile
from typing import Dict, Mapping, Tuple

from app_core.lca_format.constants import (
    DEFAULT_KEY_ID,
    LCA_FLAGS,
    LCA_FORMAT_VERSION,
    LCA_HEADER_SIZE,
    LCA_MAGIC,
    SCRIPTS_PAYLOAD_NAME,
    USER_ERROR_INVALID,
)
from app_core.lca_format.crypto import CryptoError, aes_gcm_decrypt, aes_gcm_encrypt
from app_core.lca_format.keys import get_aes_key

MAX_ZIP_MEMBERS = 10_000
MAX_ZIP_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ZIP_MEMBER_COMPRESSION_RATIO = 1_000.0
ZIP_MAGIC = b"PK"


class LcaFormatError(RuntimeError):
    """LCA 工程包格式错误。"""


def _normalize_member(path: object) -> str:
    return str(path or "").replace("\\", "/").lstrip("/")


def _is_script_member(path: object) -> bool:
    normalized = _normalize_member(path)
    if normalized in {SCRIPTS_PAYLOAD_NAME, "manifest.json"}:
        return False
    return normalized.startswith("workflows/") and normalized.endswith(".json")


def _build_aad(*, ver: int, flags: int, key_id: int) -> bytes:
    return LCA_MAGIC + struct.pack("<HHH", ver, flags, key_id)


def _files_to_zip_bytes(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(_normalize_member(path), data)
    return buffer.getvalue()


def _zip_bytes_to_files(
    plain_zip: bytes,
    *,
    max_members: int = MAX_ZIP_MEMBERS,
    max_uncompressed_bytes: int = MAX_ZIP_UNCOMPRESSED_BYTES,
    max_compression_ratio: float = MAX_ZIP_MEMBER_COMPRESSION_RATIO,
) -> Dict[str, bytes]:
    buffer = io.BytesIO(plain_zip)
    with zipfile.ZipFile(buffer, "r") as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise LcaFormatError(USER_ERROR_INVALID)

        total_size = 0
        for member in members:
            total_size += member.file_size
            if total_size > max_uncompressed_bytes:
                raise LcaFormatError(USER_ERROR_INVALID)
            if member.file_size:
                ratio = member.file_size / max(member.compress_size, 1)
                if ratio > max_compression_ratio:
                    raise LcaFormatError(USER_ERROR_INVALID)

        return {
            _normalize_member(member.filename): archive.read(member)
            for member in members
            if not member.is_dir()
        }


def _seal_lca1_blob(files: Mapping[str, bytes], *, key_id: int = DEFAULT_KEY_ID) -> bytes:
    plain_zip = _files_to_zip_bytes(files)
    ver = LCA_FORMAT_VERSION
    flags = LCA_FLAGS
    key = get_aes_key(key_id)
    aad = _build_aad(ver=ver, flags=flags, key_id=key_id)
    nonce, ciphertext_with_tag = aes_gcm_encrypt(key, plain_zip, aad=aad)
    header = LCA_MAGIC + struct.pack("<HHH", ver, flags, key_id) + nonce
    return header + ciphertext_with_tag


def _unseal_lca1_blob(blob: bytes) -> Dict[str, bytes]:
    if len(blob) < LCA_HEADER_SIZE + 16:
        raise LcaFormatError(USER_ERROR_INVALID)

    if blob[: len(LCA_MAGIC)] != LCA_MAGIC:
        raise LcaFormatError(USER_ERROR_INVALID)

    ver, flags, key_id = struct.unpack("<HHH", blob[len(LCA_MAGIC) : len(LCA_MAGIC) + 6])

    if ver != LCA_FORMAT_VERSION:
        raise LcaFormatError(USER_ERROR_INVALID)

    if flags != LCA_FLAGS:
        raise LcaFormatError(USER_ERROR_INVALID)

    nonce = blob[len(LCA_MAGIC) + 6 : LCA_HEADER_SIZE]
    ciphertext_with_tag = blob[LCA_HEADER_SIZE:]

    try:
        key = get_aes_key(key_id)
    except KeyError:
        raise LcaFormatError(USER_ERROR_INVALID) from None

    aad = _build_aad(ver=ver, flags=flags, key_id=key_id)
    try:
        plain_zip = aes_gcm_decrypt(key, nonce, ciphertext_with_tag, aad=aad)
    except CryptoError:
        raise LcaFormatError(USER_ERROR_INVALID) from None

    try:
        return _zip_bytes_to_files(plain_zip)
    except (zipfile.BadZipFile, OSError):
        raise LcaFormatError(USER_ERROR_INVALID) from None


def _split_script_and_resource_files(
    files: Mapping[str, bytes],
) -> Tuple[Dict[str, bytes], Dict[str, bytes]]:
    script_files: Dict[str, bytes] = {}
    resource_files: Dict[str, bytes] = {}
    for path, data in files.items():
        normalized = _normalize_member(path)
        if normalized == SCRIPTS_PAYLOAD_NAME:
            continue
        if _is_script_member(normalized):
            script_files[normalized] = bytes(data)
        else:
            resource_files[normalized] = bytes(data)
    return script_files, resource_files


def _patch_manifest(resource_files: Dict[str, bytes]) -> None:
    raw = resource_files.get("manifest.json")
    if raw is None:
        return
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return
    if not isinstance(manifest, dict):
        return
    manifest["schema_version"] = 2
    manifest["scripts_payload"] = SCRIPTS_PAYLOAD_NAME
    resource_files["manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=4,
    ).encode("utf-8")


def seal_lca_bytes(files: Mapping[str, bytes]) -> bytes:
    script_files, resource_files = _split_script_and_resource_files(files)
    _patch_manifest(resource_files)
    resource_files[SCRIPTS_PAYLOAD_NAME] = _seal_lca1_blob(script_files)
    return _files_to_zip_bytes(resource_files)


def unseal_lca_bytes(blob: bytes) -> Dict[str, bytes]:
    if not blob.startswith(ZIP_MAGIC):
        raise LcaFormatError(USER_ERROR_INVALID)
    try:
        outer = _zip_bytes_to_files(blob)
    except (zipfile.BadZipFile, OSError):
        raise LcaFormatError(USER_ERROR_INVALID) from None
    payload = outer.get(SCRIPTS_PAYLOAD_NAME)
    if payload is None:
        raise LcaFormatError(USER_ERROR_INVALID)
    scripts = _unseal_lca1_blob(payload)
    merged = {path: data for path, data in outer.items() if path != SCRIPTS_PAYLOAD_NAME}
    merged.update(scripts)
    return merged
