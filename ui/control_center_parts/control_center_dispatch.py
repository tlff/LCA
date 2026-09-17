from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Iterable, List, Mapping, NamedTuple, Optional, Set, Tuple

CONTROL_CENTER_DEAD_HWND_MESSAGE = "目标窗口已失效"
CONTROL_CENTER_AMBIGUOUS_HWND_MESSAGE = "目标窗口无法唯一确认"


class HwndLeaseRefresh(NamedTuple):
    window_id: str
    hwnd: int


class DeadRunningWindow(NamedTuple):
    window_id: str
    message: str


def is_runner_occupying_window(runner: Any) -> bool:
    if runner is None:
        return False
    if getattr(runner, "_task_completed_emitted", False):
        return False
    if getattr(runner, "_thread_start_requested", False):
        return True
    return bool(getattr(runner, "is_running", False))


def collect_busy_window_ids(window_runners: Optional[Mapping[Any, Any]]) -> Set[str]:
    busy: Set[str] = set()
    for window_id, runners in (window_runners or {}).items():
        items = runners if isinstance(runners, list) else [runners]
        if any(is_runner_occupying_window(runner) for runner in items):
            busy.add(str(window_id))
    return busy


def partition_serial_dispatch(
    queue: Iterable[Any],
    busy_window_ids: Optional[Iterable[str]],
) -> Tuple[Any, Deque[Any]]:
    busy = {str(window_id) for window_id in (busy_window_ids or [])}
    leftover: Deque[Any] = deque()
    chosen = None
    for runner in queue:
        if runner is None:
            continue
        window_id = str(getattr(runner, "window_id", "") or "")
        if chosen is None and (not window_id or window_id not in busy):
            chosen = runner
            continue
        leftover.append(runner)
    return chosen, leftover


def runner_target_hwnd(runner: Any) -> int:
    hwnd = getattr(runner, "hwnd", 0) or 0
    if not hwnd:
        info = getattr(runner, "window_info", None) or {}
        if isinstance(info, dict):
            hwnd = info.get("hwnd") or 0
    try:
        return int(hwnd)
    except (TypeError, ValueError):
        return 0


def _occupying_runners(runners: Any) -> List[Any]:
    items = runners if isinstance(runners, list) else [runners]
    return [runner for runner in items if is_runner_occupying_window(runner)]


def evaluate_running_window_leases(
    window_runners: Optional[Mapping[Any, Any]],
    is_alive: Callable[[int], bool],
    resolve_hwnd: Optional[Callable[[dict], int]] = None,
) -> Tuple[List[HwndLeaseRefresh], List[DeadRunningWindow]]:
    """按完整身份刷新 HWND 租约；只有无法唯一解析且旧句柄已死才判失效。"""
    refreshes: List[HwndLeaseRefresh] = []
    dead: List[DeadRunningWindow] = []
    for window_id, runners in (window_runners or {}).items():
        occupying = _occupying_runners(runners)
        if not occupying:
            continue
        runner = occupying[0]
        old_hwnd = runner_target_hwnd(runner)
        window_info = getattr(runner, "window_info", None)
        resolved = 0
        if resolve_hwnd is not None and isinstance(window_info, dict):
            try:
                resolved = int(resolve_hwnd(window_info) or 0)
            except (TypeError, ValueError):
                resolved = 0
        if resolved and is_alive(resolved):
            if resolved != old_hwnd:
                refreshes.append(HwndLeaseRefresh(str(window_id), resolved))
            continue
        if old_hwnd and is_alive(old_hwnd):
            continue
        if not old_hwnd and resolve_hwnd is None:
            continue
        if resolve_hwnd is not None and not resolved:
            message = CONTROL_CENTER_AMBIGUOUS_HWND_MESSAGE
        else:
            message = CONTROL_CENTER_DEAD_HWND_MESSAGE
        dead.append(DeadRunningWindow(str(window_id), message))
    return refreshes, dead


def refresh_occupying_runner_hwnd_leases(
    window_runners: Optional[Mapping[Any, Any]],
    is_alive: Callable[[int], bool],
    resolve_hwnd: Callable[[dict], int],
    on_refresh: Optional[Callable[[str, int], None]] = None,
) -> List[DeadRunningWindow]:
    refreshes, dead = evaluate_running_window_leases(
        window_runners,
        is_alive,
        resolve_hwnd,
    )
    mapping = window_runners or {}
    for item in refreshes:
        runners = mapping.get(item.window_id)
        if runners is None:
            runners = mapping.get(str(item.window_id), [])
        for runner in _occupying_runners(runners):
            apply_lease = getattr(runner, "apply_hwnd_lease", None)
            if callable(apply_lease):
                apply_lease(item.hwnd)
        if callable(on_refresh):
            on_refresh(item.window_id, item.hwnd)
    return dead


def collect_dead_running_window_ids(
    window_runners: Optional[Mapping[Any, Any]],
    is_alive: Callable[[int], bool],
    resolve_hwnd: Optional[Callable[[dict], int]] = None,
) -> List[str]:
    _refreshes, dead = evaluate_running_window_leases(
        window_runners,
        is_alive,
        resolve_hwnd,
    )
    return [item.window_id for item in dead]


def select_unnotified_ids(
    candidate_ids: Optional[Iterable[Any]],
    already_notified: Optional[Iterable[Any]],
) -> List[str]:
    seen_notified = {str(item) for item in (already_notified or [])}
    selected: List[str] = []
    seen_new: Set[str] = set()
    for item in candidate_ids or []:
        window_id = str(item)
        if not window_id or window_id in seen_notified or window_id in seen_new:
            continue
        seen_new.add(window_id)
        selected.append(window_id)
    return selected


def format_runner_runtime_alert(kind: str, title_or_card: Any, message: Any) -> str:
    text = str(message or "").strip()
    label = str(title_or_card if title_or_card is not None else "").strip()
    if str(kind or "").strip().lower() == "error":
        if label:
            return f"错误[{label}]: {text}".rstrip()
        return f"错误: {text}".rstrip()
    if label:
        return f"{label}: {text}".rstrip()
    return text
