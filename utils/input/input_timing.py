#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输入链路统一时序常量。
"""

from __future__ import annotations

import ctypes
from typing import List, Tuple

# 成熟方案默认值：按键按住 75ms，点击按住 50ms，双击间隔 50ms。
DEFAULT_KEY_HOLD_SECONDS = 0.075
DEFAULT_CLICK_HOLD_SECONDS = 0.050
DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS = 0.050


def read_system_keyboard_repeat() -> Tuple[float, float]:
    """读取系统键盘重复参数，返回 (首次重复延迟秒, 连发间隔秒)。"""
    delay_index = ctypes.c_int(0)
    if not ctypes.windll.user32.SystemParametersInfoW(22, 0, ctypes.byref(delay_index), 0):
        raise RuntimeError("读取键盘重复延迟失败")
    if delay_index.value < 0 or delay_index.value > 3:
        raise RuntimeError("键盘重复延迟无效")
    delay = (int(delay_index.value) + 1) * 0.25

    speed = ctypes.c_int(0)
    if not ctypes.windll.user32.SystemParametersInfoW(10, 0, ctypes.byref(speed), 0):
        raise RuntimeError("读取键盘重复速率失败")
    if speed.value < 0 or speed.value > 31:
        raise RuntimeError("键盘重复速率无效")
    repeats_per_second = 2.5 + int(speed.value) * (27.5 / 31.0)
    interval = 1.0 / repeats_per_second
    return delay, interval


def plan_key_repeat_times(duration: float, delay: float, interval: float) -> List[float]:
    """首次按下在 0 秒。返回之后应补发的时间点，均落在 [0, duration) 内。"""
    hold = max(0.0, float(duration))
    first_repeat = max(0.0, float(delay))
    step = max(1e-6, float(interval))
    times: List[float] = []
    t = first_repeat
    while t < hold:
        times.append(t)
        t += step
    return times

# 随机持续时间（仅在显式选择“随机持续时间”时使用）。
DEFAULT_RANDOM_KEY_HOLD_MIN_SECONDS = 0.050
DEFAULT_RANDOM_KEY_HOLD_MAX_SECONDS = 0.100
DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS = 0.030
DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS = 0.080
