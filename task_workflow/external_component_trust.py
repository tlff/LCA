# -*- coding: utf-8 -*-
"""Local, content-bound trust grants for scripts that invoke external code."""

from __future__ import annotations

import hashlib
from typing import Iterable


TRUST_SETTING = "script_editor/trusted_external_component_sources"
MAX_TRUSTED_SOURCES = 256


def source_digest(source: str) -> str:
    return hashlib.sha256(str(source or "").encode("utf-8")).hexdigest()


def _settings():
    from utils.instance_runtime import create_app_settings

    return create_app_settings()


def _normalize_hashes(values: Iterable[object]) -> list[str]:
    result = []
    for value in values:
        text = str(value or "").strip().lower()
        if len(text) == 64 and all(char in "0123456789abcdef" for char in text) and text not in result:
            result.append(text)
    return result[-MAX_TRUSTED_SOURCES:]


def trusted_source_hashes() -> list[str]:
    try:
        raw = _settings().value(TRUST_SETTING, [])
    except Exception:
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        values = []
    return _normalize_hashes(values)


def is_external_script_trusted(source: str) -> bool:
    try:
        from app_core.player.loader import is_player_mode_requested, is_player_only_executable

        if is_player_only_executable() or is_player_mode_requested():
            return True
    except Exception:
        pass
    return source_digest(source) in trusted_source_hashes()


def grant_external_script_trust(source: str) -> str:
    digest = source_digest(source)
    hashes = trusted_source_hashes()
    if digest not in hashes:
        hashes.append(digest)
    _settings().setValue(TRUST_SETTING, _normalize_hashes(hashes))
    return digest


def revoke_external_script_trust(source: str) -> bool:
    digest = source_digest(source)
    hashes = trusted_source_hashes()
    filtered = [item for item in hashes if item != digest]
    if len(filtered) == len(hashes):
        return False
    _settings().setValue(TRUST_SETTING, filtered)
    return True


__all__ = [
    "grant_external_script_trust",
    "is_external_script_trusted",
    "revoke_external_script_trust",
    "source_digest",
]
