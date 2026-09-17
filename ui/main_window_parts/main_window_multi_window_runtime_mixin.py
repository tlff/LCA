import logging

from PySide6.QtWidgets import QMessageBox

from task_workflow.thread_start import THREAD_START_TASK_TYPE, is_thread_start_task_type

logger = logging.getLogger(__name__)


class MainWindowMultiWindowRuntimeMixin:
    def _run_multi_window_workflow(self):
        """执行多窗口工作流（支持多个工作流合并执行）"""
        logger.info("开始多窗口工作流执行")
        # ===【新增】检查并自动应用参数面板===
        if hasattr(self, 'parameter_panel') and self.parameter_panel.is_panel_open():
            logger.info("[多窗口执行前检查] 发现参数面板处于打开状态，自动应用并关闭")
            self.parameter_panel.apply_and_close()
        # =====================================
        from utils.window.window_identity import refresh_bound_windows
        refresh_bound_windows(self.bound_windows)
        # 检查是否有启用的窗口
        enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]
        if not enabled_windows:
            QMessageBox.warning(self, "提示", "没有启用的窗口，请在全局设置中添加并启用窗口")
            return
        # 获取所有启用的工作流任务
        enabled_tasks = self.task_manager.get_enabled_tasks()
        runtime_task = None
        logger.info(f"多窗口执行: 找到 {len(enabled_tasks)} 个启用的工作流任务")
        # 如果只有一个启用的任务，使用该任务的工作流
        if len(enabled_tasks) == 1:
            task = enabled_tasks[0]
            runtime_task = task
            logger.info(f"多窗口执行: 使用单个工作流任务 '{task.name}'")
            # 【关键修复】从画布获取最新的序列化数据，而不是使用缓存的 task.workflow_data
            workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)
            if workflow_view:
                workflow_data = workflow_view.serialize_workflow()
                logger.info("多窗口执行: 从画布获取最新工作流数据")
            else:
                workflow_data = task.workflow_data
                logger.warning("多窗口执行: 无法获取画布，使用缓存的 workflow_data")
        elif len(enabled_tasks) > 1:
            # 多个工作流任务，合并为一个
            logger.info(f"多窗口执行: 合并 {len(enabled_tasks)} 个工作流任务")
            workflow_data = self._merge_workflows(enabled_tasks)
            if not workflow_data:
                QMessageBox.warning(self, "提示", "合并工作流失败，请检查工作流配置")
                return
        else:
            # 没有启用的任务，使用当前画布的工作流
            logger.info("多窗口执行: 没有启用的工作流任务，使用当前画布")
            # 工具 修复：检查 workflow_view 是否存在
            if not self.workflow_view:
                logger.error("多窗口执行: 当前画布不存在（workflow_view为None）")
                QMessageBox.warning(self, "提示", "没有可执行的工作流。\n\n请先创建或导入工作流后再执行。")
                return
            workflow_data = self.workflow_view.serialize_workflow()
            try:
                current_task_id = self.workflow_tab_widget.get_current_task_id()
                runtime_task = self.task_manager.get_task(current_task_id)
            except Exception:
                runtime_task = None
        # 工具 关键修复：补充必要的配置信息到workflow_data
        # 确保多窗口执行器能获得和单窗口相同的配置
        if 'task_modules' not in workflow_data or not workflow_data['task_modules']:
            workflow_data['task_modules'] = self.task_modules
            logger.info("多窗口执行: 添加task_modules到workflow_data")
        task_images_dir = getattr(runtime_task, "images_dir", None) if runtime_task is not None else None
        task_sounds_dir = getattr(runtime_task, "sounds_dir", None) if runtime_task is not None else None
        if not workflow_data.get('images_dir'):
            workflow_data['images_dir'] = task_images_dir or self.images_dir
            logger.info(f"多窗口执行: 添加images_dir到workflow_data: {workflow_data['images_dir']}")
        if not workflow_data.get('sounds_dir'):
            workflow_data['sounds_dir'] = task_sounds_dir
        # 验证关键配置
        if not workflow_data.get('task_modules'):
            logger.error("多窗口执行: task_modules为空，无法执行")
            QMessageBox.warning(self, "配置错误", "任务模块未加载，请重启软件后重试")
            return
        if not workflow_data.get('images_dir'):
            logger.warning("多窗口执行: images_dir为空，图片路径可能解析失败")
            # 不阻止执行，因为可能没有使用图片的任务
        # 检查工作流是否为空
        if not workflow_data or not workflow_data.get("cards"):
            QMessageBox.warning(self, "提示", "工作流为空，请添加任务卡片或启用工作流任务")
            return
        # 调试：检查工作流数据
        cards_data = workflow_data.get("cards", [])
        logger.info(f"多窗口执行: 合并后的工作流包含 {len(cards_data)} 个卡片")
        # 检查是否有线程起点卡片
        start_cards = [
            card for card in cards_data
            if is_thread_start_task_type(card.get('task_type'))
        ]
        logger.info(f"多窗口执行: 找到 {len(start_cards)} 个线程起点卡片")
        if len(start_cards) == 0:
            logger.error(f"多窗口执行: 未找到{THREAD_START_TASK_TYPE}卡片")
            logger.debug(f"多窗口执行: 所有卡片类型: {[(card.get('id'), card.get('task_type')) for card in cards_data]}")
            QMessageBox.warning(self, "提示", f"工作流中必须包含至少一个'{THREAD_START_TASK_TYPE}'卡片才能执行")
            return
        else:
            start_ids = [card.get('id') for card in start_cards if card.get('id') is not None]
            if len(start_cards) == 1:
                logger.info(f"多窗口执行: 线程起点卡片验证通过，ID: {start_cards[0].get('id')}")
            else:
                logger.info(f"多窗口执行: 多线程起点验证通过，将并发执行 {len(start_cards)} 个线程起点: {start_ids}")
        # 保存工作流（如果需要）
        if not self._save_before_execution():
            return
        # 检查前台模式限制：只有单个工作流时才能使用前台模式
        if len(enabled_tasks) > 1:
            # 多个工作流必须使用后台模式
            if not (self.current_execution_mode or '').startswith('background'):
                QMessageBox.warning(
                    self, "执行模式提示",
                    "多个工作流只能使用后台模式\n请在全局设置中将执行模式切换为后台模式"
                )
                return
        # 多窗口模式强制使用后台模式
        if not (self.current_execution_mode or '').startswith('background'):
            reply = QMessageBox.question(
                self, "执行模式确认",
                "多窗口模式需要使用后台模式，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        from utils.window.virtual_desktop import should_block_execution_start

        block_message = should_block_execution_start(
            getattr(self, "current_execution_mode", None),
            hwnds=[window.get("hwnd") for window in enabled_windows],
        )
        if block_message:
            logger.warning("前台执行被虚拟桌面策略取消")
            QMessageBox.warning(self, "无法执行", block_message)
            return
        if hasattr(self, 'multi_executor') and self.multi_executor:
            logger.info("清理旧的多窗口会话...")
            try:
                self.multi_executor.execution_progress.disconnect()
                self.multi_executor.execution_completed.disconnect()
                self.multi_executor.card_executing.disconnect()
                self.multi_executor.card_finished.disconnect()
                self.multi_executor.error_occurred.disconnect()
                self.multi_executor.show_warning.disconnect()
                if hasattr(self.multi_executor, 'cleanup'):
                    self.multi_executor.cleanup()
                logger.info("旧的多窗口会话已清理")
            except Exception as e:
                logger.warning(f"清理旧会话时出错: {e}")
        try:
            from ui.window_session.session_controller import WindowSessionController

            for window_info in enabled_windows:
                hwnd = window_info.get("hwnd")
                if hwnd:
                    try:
                        self._force_refresh_dpi_info(window_info, hwnd)
                    except Exception:
                        pass

            logger.info("创建窗口会话控制器...")
            self.multi_executor = WindowSessionController(self)
            self.multi_executor.execution_progress.connect(self._on_multi_window_progress)
            self.multi_executor.execution_completed.connect(self._on_multi_window_completed)
            self.multi_executor.card_executing.connect(self._handle_card_executing)
            self.multi_executor.card_finished.connect(self._handle_card_finished)
            self.multi_executor.error_occurred.connect(self._on_multi_window_error)
            self.multi_executor.show_warning.connect(self._show_warning_dialog)
            runtime_execution_mode = (
                self.current_execution_mode if hasattr(self, 'current_execution_mode') else 'background_sendmessage'
            )
            workflow_payload = dict(workflow_data) if isinstance(workflow_data, dict) else {}
            workflow_payload['execution_mode'] = runtime_execution_mode
            workflow_filepath = None
            if runtime_task is not None and len(enabled_tasks) <= 1:
                workflow_filepath = getattr(runtime_task, 'filepath', None)
                workflow_payload['_workflow_filepath'] = workflow_filepath
            try:
                delay_ms = int(self.multi_window_delay or 0)
            except (TypeError, ValueError):
                delay_ms = 0
            runtime_config = self.config if isinstance(getattr(self, "config", None), dict) else None
            logger.info(
                f"多窗口执行配置: 执行模式={runtime_execution_mode}, 延迟={delay_ms}ms, 窗口数={len(enabled_windows)}"
            )
            started = self.multi_executor.start_execution(
                workflow_data=workflow_payload,
                bound_windows=list(self.bound_windows or []),
                task_modules=workflow_payload.get("task_modules") or self.task_modules,
                delay_ms=delay_ms,
                execution_mode=runtime_execution_mode,
                workflow_filepath=workflow_filepath,
                runtime_config=runtime_config,
            )
            if started:
                logger.info("多窗口会话已启动")
                self._runtime_pause_owner = 'multi_executor'
                self._runtime_stop_owner = 'multi_executor'
                self._setup_multi_window_stop_button()
            else:
                logger.error("多窗口执行启动失败：没有可确认的目标窗口")
                QMessageBox.warning(
                    self,
                    "多窗口执行失败",
                    "无法确认任何绑定窗口。\n\n请检查目标窗口是否已打开，并在全局设置中重新绑定窗口。",
                )
                self._reset_run_button()
        except Exception as e:
            logger.error(f"多窗口执行启动失败: {e}")
            QMessageBox.critical(self, "执行失败", f"多窗口执行启动失败:\n{e}")
            self._reset_run_button()
