# -*- coding: utf-8 -*-
"""大漠 BindWindow(Ex) 的 mouse / keypad / mode / input display 枚举。"""

from __future__ import annotations

from utils.capture.engine_ids import PLUGIN_SCREENSHOT_ENGINES, to_dm_display_mode

PLUGIN_BIND_GROUP_BASIC = "基础绑定"
PLUGIN_BIND_GROUP_EX = "高级绑定"

PLUGIN_BIND_KIND_BASIC = "basic"
PLUGIN_BIND_KIND_ADVANCED = "advanced"
PLUGIN_BIND_KINDS = (PLUGIN_BIND_KIND_BASIC, PLUGIN_BIND_KIND_ADVANCED)

PLUGIN_IME_PUBLIC_OPTION = "dx.public.input.ime"

# BindWindow 缩写；BindWindowEx 也接受这些值。
BINDWINDOW_MOUSE_MODES = (
    "normal",
    "windows",
    "windows2",
    "windows3",
    "dx",
    "dx2",
)
# BindWindowEx 鼠标明细；只能走 BindWindowEx。
BINDWINDOWEX_MOUSE_MODES = (
    "dx.mouse.position.lock.api",
    "dx.mouse.position.lock.message",
    "dx.mouse.focus.input.api",
    "dx.mouse.focus.input.message",
    "dx.mouse.clip.lock.api",
    "dx.mouse.input.lock.api",
    "dx.mouse.input.lock.message",
    "dx.mouse.input.lock.api2",
    "dx.mouse.input.lock.api3",
    "dx.mouse.state.api",
    "dx.mouse.state.message",
    "dx.mouse.api",
    "dx.mouse.api.lock.api",
    "dx.mouse.api.lock.message",
    "dx.mouse.cursor",
    "dx.mouse.raw.input",
)
PLUGIN_MOUSE_MODES = BINDWINDOW_MOUSE_MODES + BINDWINDOWEX_MOUSE_MODES

BINDWINDOW_KEYPAD_MODES = (
    "normal",
    "windows",
    "dx",
)
BINDWINDOWEX_KEYPAD_MODES = (
    "dx.keypad.input.lock.api",
    "dx.keypad.state.api",
    "dx.keypad.api",
    "dx.keypad.raw.input",
)
PLUGIN_KEYPAD_MODES = BINDWINDOW_KEYPAD_MODES + BINDWINDOWEX_KEYPAD_MODES

# 官方 BindWindow mode：0–7；11/13 需驱动；101/103 为超级绑定。
BINDWINDOW_MODE_PRESETS = (0, 1, 2, 3, 4, 5, 6, 7)
BINDWINDOWEX_MODE_PRESETS = (11, 13, 101, 103)
PLUGIN_BIND_MODE_PRESETS = BINDWINDOW_MODE_PRESETS + BINDWINDOWEX_MODE_PRESETS

# BindWindowEx public。dx.public.input.ime 由「文本走输入法通道」单独控制，不进此表。
PLUGIN_PUBLIC_OPTIONS = (
    "dx.public.active.api",
    "dx.public.active.message",
    "dx.public.disable.window.position",
    "dx.public.disable.window.size",
    "dx.public.disable.window.minmax",
    "dx.public.fake.window.min",
    "dx.public.hide.dll",
    "dx.public.active.api2",
    "dx.public.graphic.protect",
    "dx.public.disable.window.show",
    "dx.public.anti.api",
    "dx.public.km.protect",
    "dx.public.prevent.block",
    "dx.public.ori.proc",
    "dx.public.down.cpu",
    "dx.public.focus.message",
    "dx.public.graphic.speed",
    "dx.public.memory",
    "dx.public.inject.super",
    "dx.public.hack.speed",
)

PLUGIN_INPUT_DISPLAYS = tuple(PLUGIN_SCREENSHOT_ENGINES)

_MOUSE_LABELS = {
    "normal": "通用",
    "windows": "Windows",
    "windows2": "Windows2",
    "windows3": "Windows3",
    "dx": "DX",
    "dx2": "DX2",
    "dx.mouse.position.lock.api": "DX · 锁定坐标(API)",
    "dx.mouse.position.lock.message": "DX · 锁定坐标(消息)",
    "dx.mouse.focus.input.api": "DX · 焦点输入(API)",
    "dx.mouse.focus.input.message": "DX · 焦点输入(消息)",
    "dx.mouse.clip.lock.api": "DX · 锁定刷新区域",
    "dx.mouse.input.lock.api": "DX · 输入锁定(API)",
    "dx.mouse.input.lock.message": "DX · 输入锁定(消息)",
    "dx.mouse.input.lock.api2": "DX · 输入锁定(API2)",
    "dx.mouse.input.lock.api3": "DX · 输入锁定(API3)",
    "dx.mouse.state.api": "DX · 锁定状态(API)",
    "dx.mouse.state.message": "DX · 锁定状态(消息)",
    "dx.mouse.api": "DX · API",
    "dx.mouse.api.lock.api": "DX · API+锁定(API)",
    "dx.mouse.api.lock.message": "DX · API+锁定(消息)",
    "dx.mouse.cursor": "DX · 光标",
    "dx.mouse.raw.input": "DX · RawInput",
}

_KEYPAD_LABELS = {
    "normal": "通用",
    "windows": "Windows",
    "dx": "DX",
    "dx.keypad.input.lock.api": "DX · 输入锁定(API)",
    "dx.keypad.state.api": "DX · 锁定状态(API)",
    "dx.keypad.api": "DX · API",
    "dx.keypad.raw.input": "DX · RawInput",
}

# 名称取自大漠 BindWindow / BindWindowEx 帮助「mode 取值」，不另起别名。
_BIND_MODE_LABELS = {
    0: "推荐模式",
    1: "和模式0效果一样",
    2: "同模式0",
    3: "同模式2",
    4: "同模式0",
    5: "同模式4",
    6: "同模式2",
    7: "同模式6",
    11: "需要加载驱动",
    13: "需要加载驱动",
    101: "超级绑定模式",
    103: "同模式101",
}

_BIND_MODE_TOOLTIPS = {
    0: "此模式比较通用，而且后台效果是最好的。",
    1: "和模式0效果一样。如果模式0失效，可以考虑这个模式。",
    2: "同模式0。如果模式0有崩溃问题，可以尝试此模式。主绑定成功后，调用主绑定的线程必须一直维持。",
    3: "同模式2。",
    4: "同模式0。如果模式0有崩溃问题，可以尝试此模式。",
    5: "同模式4。",
    6: "同模式2。",
    7: "同模式6。",
    11: "需要加载驱动，适合一些特殊的窗口。如果前面的无法绑定，可以尝试此模式。不支持32位系统。",
    13: "需要加载驱动，适合一些特殊的窗口。如果前面的无法绑定，可以尝试此模式。不支持32位系统。",
    101: "超级绑定模式。可隐藏目标进程中的 dm.dll，避免被恶意检测。效果比 dx.public.hide.dll 好。",
    103: "同模式101。如果模式101有崩溃问题，可以尝试此模式。",
}

_PUBLIC_LABELS = {
    "dx.public.active.api": "锁定激活(API)",
    "dx.public.active.message": "锁定激活(消息)",
    "dx.public.disable.window.position": "锁定窗口位置",
    "dx.public.disable.window.size": "禁止改变大小",
    "dx.public.disable.window.minmax": "禁止最大最小化",
    "dx.public.fake.window.min": "最小化仍可操作",
    "dx.public.hide.dll": "隐藏 DLL",
    "dx.public.active.api2": "锁定激活(API2)",
    "dx.public.graphic.protect": "保护图色",
    "dx.public.disable.window.show": "禁止窗口显示",
    "dx.public.anti.api": "突破后台保护",
    "dx.public.km.protect": "保护键鼠",
    "dx.public.prevent.block": "防止绑定卡死",
    "dx.public.ori.proc": "保持键鼠一致",
    "dx.public.down.cpu": "降低目标 CPU",
    "dx.public.focus.message": "焦点窗口收键",
    "dx.public.graphic.speed": "提高图色速度",
    "dx.public.memory": "突破内存防护",
    "dx.public.inject.super": "超级注入",
    "dx.public.hack.speed": "变速齿轮",
}

_PUBLIC_TOOLTIPS = {
    "dx.public.active.api": "封锁系统 API 锁定窗口激活。部分窗口会很耗资源。",
    "dx.public.active.message": "封锁系统消息锁定窗口激活。绑定前窗口必须已激活。",
    "dx.public.disable.window.position": "锁定绑定窗口位置。不可与「最小化仍可操作」同时用。",
    "dx.public.disable.window.size": "禁止改变窗口大小。不可与「最小化仍可操作」同时用。",
    "dx.public.disable.window.minmax": "禁止最大化和最小化，窗口会被置顶。不可与「最小化仍可操作」同时用。",
    "dx.public.fake.window.min": "最小化后仍可操作。多开会打乱任务栏，图色可能不刷新。",
    "dx.public.hide.dll": "隐藏目标进程里的大漠插件。可能导致目标崩溃，先做测试。",
    "dx.public.active.api2": "封锁系统 API 锁定激活。窗口被遮挡无法后台时用。",
    "dx.public.graphic.protect": "保护 DX 图色，对 dx.mouse.api / dx.keypad.api 也有保护。",
    "dx.public.disable.window.show": "禁止目标窗口显示，通常配合「最小化仍可操作」。",
    "dx.public.anti.api": "突破部分窗口对后台的保护。",
    "dx.public.km.protect": "保护 DX 键鼠。建议与「突破后台保护」一起用，可能让部分后台失效。",
    "dx.public.prevent.block": "模式 1/3/5/7/101/103 可能导致窗口卡死，这个属性用来避免卡死。",
    "dx.public.ori.proc": "仅用于模式 0/1/2/3/101。不同界面键鼠效果不一致时再开。",
    "dx.public.down.cpu": "配合 DownCpu 降低目标进程占用。",
    "dx.public.focus.message": "强制键盘消息发到焦点窗口。可能导致后台键盘失灵。",
    "dx.public.graphic.speed": "牺牲目标窗口性能来提高 DX 图色速度。",
    "dx.public.memory": "启用大漠内存、搜索、内存管理和汇编命令；目标进程必须允许插件访问。",
    "dx.public.inject.super": "突破某些难以绑定的窗口。对模式 0 和 2 无效。",
    "dx.public.hack.speed": "类似变速齿轮，配合 HackSpeed 使用。",
}

_MOUSE_SET = frozenset(PLUGIN_MOUSE_MODES)
_KEYPAD_SET = frozenset(PLUGIN_KEYPAD_MODES)
_BIND_MODE_SET = frozenset(PLUGIN_BIND_MODE_PRESETS)
_PUBLIC_SET = frozenset(PLUGIN_PUBLIC_OPTIONS)


def iter_plugin_mouse_ui_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        (PLUGIN_BIND_GROUP_BASIC, BINDWINDOW_MOUSE_MODES),
        (PLUGIN_BIND_GROUP_EX, BINDWINDOWEX_MOUSE_MODES),
    )


def iter_plugin_keypad_ui_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        (PLUGIN_BIND_GROUP_BASIC, BINDWINDOW_KEYPAD_MODES),
        (PLUGIN_BIND_GROUP_EX, BINDWINDOWEX_KEYPAD_MODES),
    )


def iter_plugin_bind_mode_ui_groups() -> tuple[tuple[str, tuple[int, ...]], ...]:
    return (
        (PLUGIN_BIND_GROUP_BASIC, BINDWINDOW_MODE_PRESETS),
        (PLUGIN_BIND_GROUP_EX, BINDWINDOWEX_MODE_PRESETS),
    )


def normalize_plugin_bind_kind(value: object) -> str:
    kind = str(value or "").strip().lower()
    if kind == PLUGIN_BIND_KIND_ADVANCED:
        return PLUGIN_BIND_KIND_ADVANCED
    if kind == PLUGIN_BIND_KIND_BASIC:
        return PLUGIN_BIND_KIND_BASIC
    raise ValueError(f"不支持的插件绑定方式: {value!r}")


def plugin_bind_kind_label(value: object) -> str:
    kind = normalize_plugin_bind_kind(value)
    return PLUGIN_BIND_GROUP_EX if kind == PLUGIN_BIND_KIND_ADVANCED else PLUGIN_BIND_GROUP_BASIC


def plugin_mouse_options_for_kind(kind: object) -> tuple[str, ...]:
    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return BINDWINDOWEX_MOUSE_MODES
    return BINDWINDOW_MOUSE_MODES


def plugin_keypad_options_for_kind(kind: object) -> tuple[str, ...]:
    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return BINDWINDOWEX_KEYPAD_MODES
    return BINDWINDOW_KEYPAD_MODES


def plugin_bind_mode_options_for_kind(kind: object) -> tuple[int, ...]:
    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return BINDWINDOWEX_MODE_PRESETS
    return BINDWINDOW_MODE_PRESETS


def plugin_display_options_for_kind(kind: object) -> tuple[str, ...]:
    from utils.capture.engine_ids import (
        PLUGIN_SCREENSHOT_BASIC_ENGINES,
        PLUGIN_SCREENSHOT_EX_ENGINES,
    )

    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return PLUGIN_SCREENSHOT_EX_ENGINES
    return PLUGIN_SCREENSHOT_BASIC_ENGINES


def pick_plugin_choice(value: object, options: tuple, default):
    """切换基础/高级时，旧值不在新集合里就用该组默认项；不模糊匹配、不擅自改成第一项。"""
    if not options:
        raise ValueError("插件选项列表为空")
    if value in options:
        return value
    if default in options:
        return default
    raise ValueError(f"插件选项无效: {value!r}")


def _is_bindwindowex_token(value: object) -> bool:
    return "." in str(value or "")


def plugin_bind_api(
    display: object = "normal",
    mouse: object = "normal",
    keypad: object = "normal",
) -> str:
    """宿主应按参数选择 BindWindow 或 BindWindowEx。"""
    tokens = (
        to_dm_display_mode(display),
        str(mouse or "").strip().lower(),
        str(keypad or "").strip().lower(),
    )
    if any(_is_bindwindowex_token(token) for token in tokens):
        return "BindWindowEx"
    return "BindWindow"


def plugin_mouse_label(value: object) -> str:
    mode = str(value or "").strip().lower()
    return _MOUSE_LABELS.get(mode, mode or "未知")


def plugin_keypad_label(value: object) -> str:
    mode = str(value or "").strip().lower()
    return _KEYPAD_LABELS.get(mode, mode or "未知")


def plugin_bind_mode_label(value: object) -> str:
    mode = normalize_plugin_bind_mode(value)
    return f"{mode} · {_BIND_MODE_LABELS[mode]}"


def plugin_bind_mode_tooltip(value: object) -> str:
    mode = normalize_plugin_bind_mode(value)
    return _BIND_MODE_TOOLTIPS[mode]


def normalize_plugin_mouse(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode not in _MOUSE_SET:
        raise ValueError(f"不支持的插件鼠标模式: {value!r}")
    return mode


def normalize_plugin_keypad(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode not in _KEYPAD_SET:
        raise ValueError(f"不支持的插件键盘模式: {value!r}")
    return mode


def normalize_plugin_bind_mode(value: object) -> int:
    try:
        mode = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"不支持的插件绑定 mode: {value!r}") from exc
    if mode not in _BIND_MODE_SET:
        raise ValueError(f"不支持的插件绑定 mode: {value!r}")
    return mode


def plugin_public_label(value: object) -> str:
    token = str(value or "").strip()
    return _PUBLIC_LABELS.get(token, token or "未知")


def plugin_public_tooltip(value: object) -> str:
    token = str(value or "").strip()
    return _PUBLIC_TOOLTIPS.get(token, token)


def normalize_plugin_public(value: object) -> tuple[str, ...]:
    if value is None or value == "" or value == []:
        return ()
    if isinstance(value, str):
        items = [part.strip() for part in value.split("|") if part.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(part).strip() for part in value if str(part).strip()]
    else:
        raise ValueError(f"不支持的插件公共属性: {value!r}")
    seen: set[str] = set()
    for item in items:
        if item == PLUGIN_IME_PUBLIC_OPTION:
            raise ValueError("dx.public.input.ime 由「文本走输入法通道」控制，不能写入公共属性列表")
        if item not in _PUBLIC_SET:
            raise ValueError(f"不支持的插件公共属性: {item!r}")
        seen.add(item)
    return tuple(item for item in PLUGIN_PUBLIC_OPTIONS if item in seen)
