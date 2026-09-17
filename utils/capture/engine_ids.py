# -*- coding: utf-8 -*-
"""截图引擎标识。原生引擎与插件 BindWindow display 共用同一套校验。"""

from __future__ import annotations

from typing import Iterable

NATIVE_SCREENSHOT_ENGINES = ("wgc", "printwindow", "gdi", "dxgi")

PLUGIN_SCREENSHOT_BASIC_ENGINES = (
    "normal",
    "plugin.gdi",
    "gdi2",
    "dx",
    "dx2",
    "dx3",
)
PLUGIN_SCREENSHOT_EX_ENGINES = (
    "dx.graphic.2d",
    "dx.graphic.2d.2",
    "dx.graphic.3d",
    "dx.graphic.3d.8",
    "dx.graphic.3d.10plus",
    "dx.graphic.opengl",
    "dx.graphic.opengl.esv2",
)
PLUGIN_SCREENSHOT_ENGINES = PLUGIN_SCREENSHOT_BASIC_ENGINES + PLUGIN_SCREENSHOT_EX_ENGINES

SUPPORTED_SCREENSHOT_ENGINES = NATIVE_SCREENSHOT_ENGINES + PLUGIN_SCREENSHOT_ENGINES
BACKGROUND_SCREENSHOT_ENGINES = ("wgc", "printwindow") + PLUGIN_SCREENSHOT_ENGINES

_SCREENSHOT_ENGINE_LABELS = {
    "wgc": "WGC",
    "printwindow": "PrintWindow",
    "gdi": "GDI",
    "dxgi": "DXGI",
    "normal": "通用",
    "plugin.gdi": "GDI",
    "gdi2": "GDI2",
    "dx": "DX",
    "dx2": "DX2",
    "dx3": "DX3",
    "dx.graphic.2d": "DX · 2D",
    "dx.graphic.2d.2": "DX · 2D增强",
    "dx.graphic.3d": "DX · 3D",
    "dx.graphic.3d.8": "DX · D3D8",
    "dx.graphic.3d.10plus": "DX · D3D10+",
    "dx.graphic.opengl": "OpenGL",
    "dx.graphic.opengl.esv2": "OpenGL ES",
}

_DM_DISPLAY_MAP = {
    "plugin.gdi": "gdi",
}

SCREENSHOT_ENGINE_UI_GROUPS = (
    ("原生", NATIVE_SCREENSHOT_ENGINES),
    ("插件", PLUGIN_SCREENSHOT_ENGINES),
)

_SUPPORTED_SET = frozenset(SUPPORTED_SCREENSHOT_ENGINES)
_PLUGIN_SET = frozenset(PLUGIN_SCREENSHOT_ENGINES)
_NATIVE_SET = frozenset(NATIVE_SCREENSHOT_ENGINES)
_BACKGROUND_SET = frozenset(BACKGROUND_SCREENSHOT_ENGINES)


def normalize_screenshot_engine(engine: object) -> str:
    return str(engine or "").strip().lower()


def canonicalize_screenshot_engine(engine: object) -> str:
    return normalize_screenshot_engine(engine)


def to_dm_display_mode(engine: object) -> str:
    raw = normalize_screenshot_engine(engine)
    mapped = _DM_DISPLAY_MAP.get(raw)
    if mapped:
        return mapped
    mode = canonicalize_screenshot_engine(engine)
    return _DM_DISPLAY_MAP.get(mode, mode)


def iter_plugin_screenshot_ui_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        ("基础绑定", PLUGIN_SCREENSHOT_BASIC_ENGINES),
        ("高级绑定", PLUGIN_SCREENSHOT_EX_ENGINES),
    )


def is_supported_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _SUPPORTED_SET


def is_plugin_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _PLUGIN_SET


def is_native_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _NATIVE_SET


def is_background_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _BACKGROUND_SET


def screenshot_engine_label(engine: object) -> str:
    normalized = normalize_screenshot_engine(engine)
    return _SCREENSHOT_ENGINE_LABELS.get(normalized, normalized or "未知引擎")


def screenshot_engine_log_label(engine: object) -> str:
    label = screenshot_engine_label(engine)
    if is_plugin_screenshot_engine(engine):
        return f"大漠({label})"
    return label


def iter_supported_screenshot_engines() -> Iterable[str]:
    return SUPPORTED_SCREENSHOT_ENGINES


def iter_screenshot_engine_ui_groups(*, background_only: bool = False) -> Iterable[tuple[str, tuple[str, ...]]]:
    for title, engines in SCREENSHOT_ENGINE_UI_GROUPS:
        filtered = engines_for_ui_group(title, background_only=background_only)
        if filtered:
            yield title, filtered


def engines_for_ui_group(group_title: object, *, background_only: bool = False) -> tuple[str, ...]:
    title = str(group_title or "").strip()
    for group_name, engines in SCREENSHOT_ENGINE_UI_GROUPS:
        if group_name != title:
            continue
        if background_only:
            return tuple(engine for engine in engines if is_background_screenshot_engine(engine))
        return tuple(engines)
    return ()


def screenshot_engine_ui_group(engine: object) -> str:
    if is_plugin_screenshot_engine(engine):
        return "插件"
    if is_native_screenshot_engine(engine):
        return "原生"
    return "原生"
