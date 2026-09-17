#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按系统键盘重复率补发按住期间的连发。"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from utils.input.input_timing import plan_key_repeat_times, read_system_keyboard_repeat

logger = logging.getLogger(__name__)


def run_system_repeat_schedule(
    *,
    repeat: Callable[[], bool],
    duration: float,
    sleep: Callable[[float], None],
    enable_repeat: bool,
    repeat_interval: Optional[float] = None,
) -> bool:
    """按住期间按延迟/速率调用 repeat；enable_repeat 为假时只等待。"""
    hold = max(0.0, float(duration))
    if hold <= 0:
        return True
    if not enable_repeat:
        sleep(hold)
        return True
    if repeat_interval is None:
        delay, interval = read_system_keyboard_repeat()
    else:
        interval = float(repeat_interval)
        if interval <= 0:
            raise ValueError("间隔必须大于0")
        delay = interval
    prev = 0.0
    for stamp in plan_key_repeat_times(hold, delay, interval):
        gap = stamp - prev
        if gap > 0:
            sleep(gap)
        if not bool(repeat()):
            return False
        prev = stamp
    remaining = hold - prev
    if remaining > 0:
        sleep(remaining)
    return True


def hold_with_system_repeat(
    *,
    down: Callable[[], bool],
    up: Callable[[], bool],
    repeat: Callable[[], bool],
    duration: float,
    sleep: Callable[[float], None],
    enable_repeat: bool = True,
    repeat_interval: Optional[float] = None,
) -> bool:
    """先按下，可选按延迟/速率调用 repeat，最后松开。"""
    if not bool(down()):
        return False
    held = True
    try:
        if not run_system_repeat_schedule(
            repeat=repeat,
            duration=duration,
            sleep=sleep,
            enable_repeat=enable_repeat,
            repeat_interval=repeat_interval,
        ):
            return False
        if not bool(up()):
            return False
        held = False
        return True
    finally:
        if held:
            try:
                up()
            except Exception:
                logger.exception("按键补松开失败")
