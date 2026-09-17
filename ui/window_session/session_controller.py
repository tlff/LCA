from __future__ import annotations

import logging
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal

from app_core.control_plane import ensure_bind_id
from ui.control_center_parts.control_center_dispatch import (
    collect_busy_window_ids,
    is_runner_occupying_window,
    partition_serial_dispatch,
    refresh_occupying_runner_hwnd_leases,
)
from ui.control_center_parts.control_center_runtime import WindowTaskRunner
from ui.control_center_parts.control_center_runtime_types import TaskState
from utils.window.window_identity import is_window_alive, resolve_bound_window_hwnd

logger = logging.getLogger(__name__)


class WindowSessionController(QObject):
    execution_completed = Signal(bool, str)
    execution_progress = Signal(str, str)
    card_executing = Signal(int)
    card_finished = Signal(int, bool)
    error_occurred = Signal(str, int, int, str)
    show_warning = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window_runners: Dict[str, List[WindowTaskRunner]] = {}
        self._runner_start_queue: Deque[WindowTaskRunner] = deque()
        self._pending_start_runners: Deque[WindowTaskRunner] = deque()
        self._window_results: Dict[str, bool] = {}
        self._skipped_failures: List[str] = []
        self._session_active = False
        self._finished_emitted = False
        self._stop_requested = False
        self._start_delay_ms = 0
        self._dispatch_in_progress = False
        self._hwnd_watchdog_timer: Optional[QTimer] = None
        self._dead_hwnd_stopped = set()
        self._enqueue_timer: Optional[QTimer] = None

    @property
    def is_running(self) -> bool:
        return bool(self._session_active)

    def get_pause_state(self) -> str:
        if not self._session_active:
            return "idle"
        running_count = 0
        paused_count = 0
        for runner in self._iter_runners():
            try:
                occupying = is_runner_occupying_window(runner)
            except Exception:
                occupying = False
            if not occupying:
                continue
            state = getattr(runner, "current_state", None)
            state_value = getattr(state, "value", state)
            if state_value in {"已暂停", "暂停中"} or state == TaskState.PAUSED:
                paused_count += 1
            else:
                running_count += 1
        if running_count > 0:
            return "running"
        if paused_count > 0:
            return "paused"
        return "running"

    def pause_all(self):
        for runner in self._iter_runners():
            try:
                runner.pause()
            except Exception as exc:
                logger.warning("暂停窗口会话失败: window_id=%s error=%s", getattr(runner, "window_id", ""), exc)

    def resume_all(self):
        for runner in self._iter_runners():
            try:
                runner.resume()
            except Exception as exc:
                logger.warning("恢复窗口会话失败: window_id=%s error=%s", getattr(runner, "window_id", ""), exc)

    def stop_all(self, force: bool = True):
        _ = force
        self._stop_requested = True
        self._pending_start_runners.clear()
        while self._runner_start_queue:
            runner = self._runner_start_queue.popleft()
            runner._queued_for_start = False
            try:
                runner.stop()
            except Exception as exc:
                logger.warning("停止排队中的窗口会话失败: %s", exc)
        for runner in list(self._iter_runners()):
            key = str(getattr(runner, "window_id", "") or "")
            if key and key not in self._window_results:
                self._window_results[key] = False
            try:
                runner.stop()
            except Exception as exc:
                logger.warning("停止窗口会话失败: window_id=%s error=%s", getattr(runner, "window_id", ""), exc)
        self._maybe_finish()

    def cleanup(self):
        self._stop_hwnd_watchdog()
        self._stop_enqueue_timer()
        if self._session_active:
            self.stop_all(force=True)

    def start_execution(
        self,
        *,
        workflow_data: Dict[str, Any],
        bound_windows: List[Dict[str, Any]],
        task_modules: Any,
        delay_ms: int = 0,
        execution_mode: Optional[str] = None,
        workflow_filepath: Optional[str] = None,
        runtime_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self._reset_session()
        try:
            delay = int(delay_ms or 0)
        except (TypeError, ValueError):
            delay = 0
        self._start_delay_ms = max(0, delay)

        enabled_windows = [
            window_info
            for window_info in (bound_windows or [])
            if isinstance(window_info, dict) and window_info.get("enabled", True)
        ]
        runtime_windows = list(bound_windows or [])
        created: List[WindowTaskRunner] = []
        for window_info in enabled_windows:
            bind_id = ensure_bind_id(window_info)
            hwnd = resolve_bound_window_hwnd(window_info)
            title = str(window_info.get("title") or bind_id or "未知窗口")
            if not hwnd:
                reason = "目标窗口无法唯一确认"
                self._skipped_failures.append(title)
                self.execution_progress.emit(title, reason)
                logger.warning("跳过无有效句柄的窗口: %s", title)
                continue
            window_info["hwnd"] = hwnd
            runner = WindowTaskRunner(
                window_info,
                workflow_data,
                task_modules,
                workflow_file_path=workflow_filepath,
                workflow_slot=0,
                bound_windows=runtime_windows,
                execution_mode=execution_mode,
                runtime_config=runtime_config,
            )
            self._connect_runner(runner)
            self.window_runners[bind_id] = [runner]
            created.append(runner)

        if not created:
            self._session_active = False
            return False

        self._session_active = True
        self._setup_hwnd_watchdog()
        self._pending_start_runners = deque(created)
        if self._start_delay_ms <= 0:
            while self._pending_start_runners:
                self._enqueue_next_runner()
            self._dispatch_pending_starts()
        else:
            self._enqueue_next_runner()
            self._dispatch_pending_starts()
            self._schedule_next_enqueue()
        return True

    def _reset_session(self) -> None:
        self._stop_hwnd_watchdog()
        self._stop_enqueue_timer()
        self.window_runners = {}
        self._runner_start_queue = deque()
        self._pending_start_runners = deque()
        self._window_results = {}
        self._skipped_failures = []
        self._session_active = False
        self._finished_emitted = False
        self._stop_requested = False
        self._dead_hwnd_stopped = set()

    def _iter_runners(self):
        for runners in self.window_runners.values():
            items = runners if isinstance(runners, list) else [runners]
            for runner in items:
                if runner is not None:
                    yield runner

    def _connect_runner(self, runner: WindowTaskRunner) -> None:
        queued = Qt.ConnectionType.QueuedConnection
        runner.status_updated.connect(self._on_runner_status, queued)
        runner.task_completed.connect(self._on_runner_task_completed, queued)
        runner.card_executing.connect(self.card_executing, queued)
        runner.card_finished.connect(self.card_finished, queued)
        runner.error_occurred.connect(self.error_occurred, queued)
        runner.show_warning.connect(self.show_warning, queued)

    def _runner_title(self, window_id: str) -> str:
        runners = self.window_runners.get(str(window_id)) or []
        if not isinstance(runners, list):
            runners = [runners]
        if runners:
            info = getattr(runners[0], "window_info", None) or {}
            title = str(info.get("title") or "").strip()
            if title:
                return title
        return str(window_id or "未知窗口")

    def _on_runner_status(self, window_id: str, status: str) -> None:
        self.execution_progress.emit(self._runner_title(window_id), str(status or ""))

    def _on_runner_task_completed(self, window_id: str, success: bool) -> None:
        key = str(window_id or "")
        if key:
            self._window_results[key] = bool(success)
        self._dispatch_pending_starts()
        self._maybe_finish()

    def _enqueue_next_runner(self) -> None:
        if self._stop_requested or not self._pending_start_runners:
            return
        runner = self._pending_start_runners.popleft()
        if getattr(runner, "_queued_for_start", False) or getattr(runner, "_thread_start_requested", False):
            return
        if getattr(runner, "_task_completed_emitted", False):
            return
        runner._queued_for_start = True
        self._runner_start_queue.append(runner)

    def _schedule_next_enqueue(self) -> None:
        if self._stop_requested or not self._pending_start_runners:
            return
        timer = self._enqueue_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._on_enqueue_timer)
            self._enqueue_timer = timer
        timer.start(self._start_delay_ms)

    def _on_enqueue_timer(self) -> None:
        self._enqueue_next_runner()
        self._dispatch_pending_starts()
        self._schedule_next_enqueue()

    def _stop_enqueue_timer(self) -> None:
        timer = self._enqueue_timer
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass

    def _dispatch_pending_starts(self) -> int:
        if self._stop_requested or self._dispatch_in_progress:
            return 0
        started_count = 0
        try:
            limit = max(1, int(WindowTaskRunner._get_execution_slot_limit()))
        except Exception:
            limit = 1
        active_count = self._count_started_threads()
        busy_window_ids = collect_busy_window_ids(self.window_runners)
        self._dispatch_in_progress = True
        try:
            while active_count < limit and self._runner_start_queue:
                runner, leftover = partition_serial_dispatch(self._runner_start_queue, busy_window_ids)
                self._runner_start_queue = leftover
                if runner is None:
                    break
                runner._queued_for_start = False
                if getattr(runner, "_task_completed_emitted", False):
                    continue
                if getattr(runner, "_should_stop", False) or self._stop_requested:
                    try:
                        runner.stop()
                    except Exception:
                        pass
                    continue
                try:
                    runner._thread_start_requested = True
                    runner.start()
                    try:
                        runner.setPriority(QThread.Priority.LowPriority)
                    except Exception as exc:
                        logger.warning("设置窗口会话线程优先级失败: %s", exc)
                    started_count += 1
                    active_count += 1
                    busy_window_ids.add(str(getattr(runner, "window_id", "") or ""))
                    logger.info(
                        "主窗口会话启动 runner: window_id=%s active=%s/%s",
                        runner.window_id,
                        active_count,
                        limit,
                    )
                except Exception as exc:
                    runner._thread_start_requested = False
                    logger.error("主窗口会话启动 runner 失败: window_id=%s error=%s", runner.window_id, exc)
                    self._window_results[str(runner.window_id or "")] = False
        finally:
            self._dispatch_in_progress = False
        return started_count

    def _count_started_threads(self) -> int:
        active_count = 0
        for runner in self._iter_runners():
            try:
                thread_running = bool(runner.isRunning())
            except Exception:
                thread_running = False
            try:
                pending_start = bool(
                    getattr(runner, "_thread_start_requested", False)
                    and not getattr(runner, "_task_completed_emitted", False)
                    and not getattr(runner, "_queued_for_start", False)
                )
            except Exception:
                pending_start = False
            if thread_running or pending_start:
                active_count += 1
        return active_count

    def _setup_hwnd_watchdog(self) -> None:
        timer = self._hwnd_watchdog_timer
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(2000)
            timer.timeout.connect(self._check_running_window_handles)
            self._hwnd_watchdog_timer = timer
        if not timer.isActive():
            timer.start()

    def _stop_hwnd_watchdog(self) -> None:
        timer = self._hwnd_watchdog_timer
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass

    def _check_running_window_handles(self) -> None:
        if not self._session_active:
            return
        dead = refresh_occupying_runner_hwnd_leases(
            self.window_runners,
            is_window_alive,
            resolve_bound_window_hwnd,
        )
        for item in dead:
            if item.window_id in self._dead_hwnd_stopped:
                continue
            self._dead_hwnd_stopped.add(item.window_id)
            title = self._runner_title(item.window_id)
            logger.warning("主窗口会话检测到目标窗口失效: window_id=%s reason=%s", item.window_id, item.message)
            self.execution_progress.emit(title, item.message)
            hwnd = 0
            for runner in self.window_runners.get(item.window_id, []):
                try:
                    hwnd = int(getattr(runner, "hwnd", 0) or 0)
                except (TypeError, ValueError):
                    hwnd = 0
                self.error_occurred.emit(title, hwnd, 0, item.message)
                try:
                    runner.stop()
                except Exception as exc:
                    logger.error("停止失效窗口会话失败: window_id=%s error=%s", item.window_id, exc)
            self._window_results[item.window_id] = False

    def _maybe_finish(self) -> None:
        if self._finished_emitted or not self._session_active:
            return
        if self._pending_start_runners or self._runner_start_queue:
            return
        for runner in self._iter_runners():
            if is_runner_occupying_window(runner):
                return
            if not getattr(runner, "_task_completed_emitted", False) and not self._stop_requested:
                if getattr(runner, "_thread_start_requested", False):
                    return
        self._emit_completed()

    def _emit_completed(self) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self._session_active = False
        self._stop_hwnd_watchdog()
        self._stop_enqueue_timer()
        success_count = sum(1 for value in self._window_results.values() if value)
        fail_count = sum(1 for value in self._window_results.values() if not value) + len(self._skipped_failures)
        overall = fail_count == 0 and success_count > 0
        message = f"多窗口执行完成：成功 {success_count} 个，失败 {fail_count} 个"
        logger.info(message)
        self.execution_completed.emit(overall, message)
