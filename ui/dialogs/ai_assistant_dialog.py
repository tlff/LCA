# -*- coding: utf-8 -*-
"""独立的 AI 助手窗口，不占用右侧参数面板。"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QUrl, Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app_core.ai_assistant import (
    AIProviderConfig,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    REVIEW_WORKFLOW_PROMPT,
    build_ai_chat_messages,
    chat_completion,
    chat_system_prompt,
    editor_workflow_context,
    load_ai_provider_settings,
    normalize_ai_base_url,
    save_ai_provider_settings,
)
from app_core.ai_workflow import apply_editor_workflow, parse_workflow_proposal
from app_core.ai_chat_format import format_ai_transcript_html
from app_core.ai_sessions import (
    append_message,
    chat_history,
    create_session,
    delete_session,
    get_session,
    load_ai_sessions,
    rename_session,
    save_ai_sessions,
    set_current_session,
)
from utils.window.window_activation_utils import show_and_raise_widget
from utils.window.window_coordinate_common import (
    center_window_on_widget_screen,
    clamp_preferred_window_size,
    get_available_geometry_for_widget,
)

logger = logging.getLogger(__name__)
SETTINGS_VISIBLE_KEY = "ai/settings_visible"
GEOMETRY_KEY = "ai/window_geometry"
_DEFAULT_STATUS = (
    "多轮对话保存在本机。每次提问都会附带当前正在编辑的工作流。"
    "审查后给出的工作流代码块可点「应用」写入当前画布。"
    "服务和 API Key 在右上角「设置」里。"
)


class _AIWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, config: AIProviderConfig, messages, parent=None):
        super().__init__(parent)
        self._config = config
        self._messages = messages

    def run(self) -> None:
        try:
            self.completed.emit(chat_completion(self._config, self._messages))
        except Exception as exc:
            self.failed.emit(str(exc))


class _AIPromptEnterFilter(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return False
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return False
        dialog = self.parent()
        if dialog is not None and hasattr(dialog, "send_current_prompt"):
            dialog.send_current_prompt()
            return True
        return False


def _widget_alive(widget) -> bool:
    if widget is None:
        return False
    try:
        from shiboken6 import isValid

        return bool(isValid(widget))
    except Exception:
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False


def open_ai_assistant_dialog(main_window):
    existing = getattr(main_window, "_ai_assistant_dialog", None) if main_window is not None else None
    if _widget_alive(existing):
        existing.refresh_for_main_window(main_window)
        show_and_raise_widget(existing, log_prefix="AI 助手")
        existing.activateWindow()
        return existing
    dialog = AIAssistantDialog(main_window)
    if main_window is not None:
        main_window._ai_assistant_dialog = dialog

        def _forget(_result=0, window=main_window, assistant=dialog) -> None:
            if getattr(window, "_ai_assistant_dialog", None) is assistant:
                window._ai_assistant_dialog = None

        dialog.finished.connect(_forget)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


class AIAssistantDialog(QDialog):
    """左侧会话、右侧对话，服务设置默认收起。"""

    def __init__(self, main_window=None):
        super().__init__(main_window)
        self.main_window = main_window
        self._store: Dict[str, Any] = {}
        self._session_id = ""
        self._loading_session = False
        self._worker: Optional[_AIWorker] = None
        self._copy_payloads: List[str] = []
        self._prompt_filter = _AIPromptEnterFilter(self)
        self._build_ui()
        self._load_sessions()
        self._load_provider_into_form()
        self._refresh_session_list()
        self._render_chat()
        self._register_theme_callback()

    def refresh_for_main_window(self, main_window=None) -> None:
        if main_window is not None:
            self.main_window = main_window

    def _build_ui(self) -> None:
        self.setObjectName("aiAssistantDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("AI 助手")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setMinimumSize(820, 540)
        available = get_available_geometry_for_widget(self.parentWidget() or self)
        width, height = clamp_preferred_window_size(980, 680, available)
        self.resize(width, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_settings_panel())
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("aiAssistantSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_session_panel())
        splitter.addWidget(self._build_chat_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 740])
        layout.addWidget(splitter, 1)
        if not self._restore_geometry():
            center_window_on_widget_screen(self, self.parentWidget())

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel("AI 助手")
        title.setObjectName("aiAssistantTitle")
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        self.settings_button = QPushButton("设置")
        self.settings_button.setCheckable(True)
        self.settings_button.setChecked(self._load_settings_visible())
        self.settings_button.clicked.connect(self._toggle_settings)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self.settings_button)
        return row

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("aiSettingsPanel")
        form = QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 4)
        form.setSpacing(6)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(DEFAULT_BASE_URL)
        self.base_url_edit.editingFinished.connect(self._complete_base_url)
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText(DEFAULT_MODEL)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("只保存在本机，不写入工作流")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(90)
        form.addRow("服务地址", self.base_url_edit)
        form.addRow("模型", self.model_edit)
        form.addRow("API Key", self.api_key_edit)
        form.addRow("超时(秒)", self.timeout_spin)
        self.settings_panel = panel
        panel.setVisible(self.settings_button.isChecked())
        return panel

    def _build_session_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("aiSessionPanel")
        panel.setMinimumWidth(180)
        panel.setMaximumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(6)
        heading = QLabel("会话")
        heading.setObjectName("aiSessionHeading")
        heading_font = heading.font()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        self.session_list = QListWidget()
        self.session_list.setObjectName("aiSessionList")
        self.session_list.currentItemChanged.connect(self._on_session_item_changed)
        new_button = QPushButton("新建")
        rename_button = QPushButton("改名")
        delete_button = QPushButton("删除")
        new_button.clicked.connect(self._on_new_session)
        rename_button.clicked.connect(self._on_rename_session)
        delete_button.clicked.connect(self._on_delete_session)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        buttons.addWidget(new_button)
        buttons.addWidget(rename_button)
        buttons.addWidget(delete_button)
        layout.addWidget(heading)
        layout.addWidget(self.session_list, 1)
        layout.addLayout(buttons)
        self._session_buttons = (new_button, rename_button, delete_button)
        return panel

    def _build_chat_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("aiChatPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)
        self.chat_view = QTextBrowser()
        self.chat_view.setObjectName("aiChatView")
        self.chat_view.setReadOnly(True)
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setOpenLinks(False)
        self.chat_view.setMinimumHeight(260)
        self.chat_view.document().setDefaultStyleSheet(
            "p { margin-top: 0px; margin-bottom: 0px; }"
            "pre { margin-top: 0px; margin-bottom: 0px; }"
        )
        self.chat_view.anchorClicked.connect(self._on_chat_anchor)
        layout.addWidget(self.chat_view, 1)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setObjectName("aiPromptEdit")
        self.prompt_edit.setPlaceholderText("输入问题，Enter 发送，Shift+Enter 换行。也可点「审查工作流」。")
        self.prompt_edit.setFixedHeight(92)
        self.prompt_edit.installEventFilter(self._prompt_filter)
        layout.addWidget(self.prompt_edit)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel(_DEFAULT_STATUS)
        self.status_label.setObjectName("aiAssistantStatus")
        self.status_label.setWordWrap(True)
        self.review_button = QPushButton("审查工作流")
        self.review_button.clicked.connect(self.review_current_workflow)
        self.send_button = QPushButton("发送")
        self.send_button.setProperty("primary", True)
        self.send_button.clicked.connect(self.send_current_prompt)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.review_button)
        footer.addWidget(self.send_button)
        layout.addLayout(footer)
        return panel

    def _register_theme_callback(self) -> None:
        try:
            from themes import get_theme_manager

            get_theme_manager().register_theme_change_callback(self._on_theme_changed)
        except Exception:
            return

        def _forget(_=None, callback=self._on_theme_changed) -> None:
            try:
                from themes import get_theme_manager

                get_theme_manager().unregister_theme_change_callback(callback)
            except Exception:
                pass

        self.destroyed.connect(_forget)

    def _on_theme_changed(self, _theme=None) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self._render_chat()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._persist_sessions()
        self._save_provider_from_form()
        self._save_window_state()
        super().closeEvent(event)

    def _load_settings_visible(self) -> bool:
        try:
            from utils.instance_runtime import create_app_settings

            return bool(create_app_settings().value(SETTINGS_VISIBLE_KEY, False, type=bool))
        except Exception:
            return False

    def _toggle_settings(self) -> None:
        visible = self.settings_button.isChecked()
        self.settings_panel.setVisible(visible)
        try:
            from utils.instance_runtime import create_app_settings

            create_app_settings().setValue(SETTINGS_VISIBLE_KEY, visible)
        except Exception:
            logger.debug("保存 AI 设置展开状态失败", exc_info=True)

    def _restore_geometry(self) -> bool:
        try:
            from utils.instance_runtime import create_app_settings

            geometry = create_app_settings().value(GEOMETRY_KEY)
            if geometry is not None:
                return bool(self.restoreGeometry(geometry))
        except Exception:
            logger.debug("恢复 AI 窗口尺寸失败", exc_info=True)
        return False

    def _save_window_state(self) -> None:
        try:
            from utils.instance_runtime import create_app_settings

            create_app_settings().setValue(GEOMETRY_KEY, self.saveGeometry())
        except Exception:
            logger.debug("保存 AI 窗口尺寸失败", exc_info=True)

    def _load_provider_into_form(self) -> None:
        values = load_ai_provider_settings()
        self.base_url_edit.setText(str(values.get("base_url") or DEFAULT_BASE_URL))
        self.model_edit.setText(str(values.get("model") or DEFAULT_MODEL))
        self.api_key_edit.setText(str(values.get("api_key") or ""))
        self.timeout_spin.setValue(int(values.get("timeout") or 90))

    def _complete_base_url(self) -> None:
        completed = normalize_ai_base_url(self.base_url_edit.text())
        if self.base_url_edit.text() != completed:
            self.base_url_edit.setText(completed)

    def _save_provider_from_form(self) -> None:
        self._complete_base_url()
        try:
            save_ai_provider_settings(
                base_url=self.base_url_edit.text(),
                model=self.model_edit.text(),
                api_key=self.api_key_edit.text(),
                timeout=int(self.timeout_spin.value()),
            )
        except Exception:
            logger.debug("保存 AI 设置失败", exc_info=True)

    def _provider_config(self) -> AIProviderConfig:
        return AIProviderConfig(
            str(self.base_url_edit.text() or "").strip(),
            str(self.model_edit.text() or "").strip(),
            str(self.api_key_edit.text() or ""),
            int(self.timeout_spin.value() or 90),
        )

    def _current_session(self) -> Optional[Dict[str, Any]]:
        return get_session(self._store, self._session_id)

    def _load_sessions(self) -> None:
        self._store = load_ai_sessions()
        current = get_session(self._store)
        if current is None:
            current = create_session(self._store)
            save_ai_sessions(self._store)
        self._session_id = str(current.get("id") or "")

    def _persist_sessions(self) -> None:
        if not self._store:
            return
        try:
            save_ai_sessions(self._store)
        except Exception:
            logger.debug("保存 AI 会话失败", exc_info=True)

    def _refresh_session_list(self) -> None:
        self._loading_session = True
        try:
            self.session_list.clear()
            current_item = None
            for session in self._store.get("sessions") or []:
                item = QListWidgetItem(str(session.get("title") or "新对话"))
                item.setData(Qt.ItemDataRole.UserRole, session.get("id"))
                self.session_list.addItem(item)
                if session.get("id") == self._session_id:
                    current_item = item
            if current_item is not None:
                self.session_list.setCurrentItem(current_item)
            elif self.session_list.count():
                self.session_list.setCurrentRow(0)
        finally:
            self._loading_session = False

    def _theme_colors(self) -> Dict[str, str]:
        from themes import theme_color

        return {
            "text": theme_color("text"),
            "muted": theme_color("text_secondary"),
            "user": theme_color("accent"),
            "assistant": theme_color("success"),
            "surface": theme_color("surface"),
            "canvas": theme_color("canvas"),
            "border": theme_color("border"),
            "accent": theme_color("accent"),
        }

    def _render_chat(self) -> None:
        if not hasattr(self, "chat_view") or self.chat_view is None:
            return
        session = self._current_session()
        html, payloads = format_ai_transcript_html(
            list((session or {}).get("messages") or []),
            self._theme_colors(),
        )
        self._copy_payloads = payloads
        self.chat_view.setHtml(html)
        scrollbar = self.chat_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_chat_anchor(self, url: QUrl) -> None:
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return
        raw = url.toString()
        index_text = raw.split(":", 1)[-1]
        try:
            index = int(index_text)
        except ValueError:
            index = -1
        if url.scheme() == "apply":
            self._apply_workflow_payload(index)
            return
        if url.scheme() != "copy":
            return
        if index < 0 or index >= len(self._copy_payloads):
            self._set_status("没有可复制的内容。")
            return
        QGuiApplication.clipboard().setText(self._copy_payloads[index])
        self._set_status("已复制。")

    def _apply_workflow_payload(self, index: int) -> None:
        if index < 0 or index >= len(self._copy_payloads):
            self._set_status("没有可应用的工作流修正。")
            return
        body = self._copy_payloads[index]
        try:
            ops = parse_workflow_proposal(body)
        except ValueError as exc:
            QMessageBox.warning(self, "无法应用", str(exc))
            self._set_status(str(exc))
            return
        choice = QMessageBox.question(
            self,
            "应用工作流",
            f"把这份修正写入当前正在编辑的工作流？共 {len(ops)} 项操作。此操作可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            result = apply_editor_workflow(self.main_window, body)
        except Exception as exc:
            QMessageBox.warning(self, "应用失败", str(exc))
            self._set_status(str(exc))
            return
        self._set_status(
            f"已应用到当前工作流：{result['ops']} 项操作，"
            f"现在有 {result['cards']} 张卡片、{result['connections']} 条连线。"
        )

    def _append_chat_message(self, role: str, content: str) -> None:
        if not self._session_id:
            self._load_sessions()
        append_message(self._store, self._session_id, role, content)
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()

    def _switch_session(self, session_id: str) -> None:
        if not session_id or session_id == self._session_id:
            return
        set_current_session(self._store, session_id)
        self._session_id = session_id
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()

    def _on_session_item_changed(self, current, _previous) -> None:
        if self._loading_session or current is None:
            return
        session_id = current.data(Qt.ItemDataRole.UserRole)
        if session_id:
            self._switch_session(str(session_id))

    def _on_new_session(self) -> None:
        session = create_session(self._store)
        self._session_id = str(session["id"])
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()
        self._set_status("已新建对话。")
        self.prompt_edit.setFocus()

    def _on_rename_session(self) -> None:
        session = self._current_session()
        if session is None:
            return
        title, ok = QInputDialog.getText(self, "重命名对话", "对话名称：", text=str(session.get("title") or ""))
        if not ok:
            return
        rename_session(self._store, self._session_id, title)
        save_ai_sessions(self._store)
        self._refresh_session_list()

    def _on_delete_session(self) -> None:
        session = self._current_session()
        if session is None:
            return
        choice = QMessageBox.question(
            self,
            "删除对话",
            f"删除「{session.get('title') or '新对话'}」？此操作不能恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        next_session = delete_session(self._store, self._session_id)
        self._session_id = str((next_session or {}).get("id") or "")
        save_ai_sessions(self._store)
        self._refresh_session_list()
        self._render_chat()
        self._set_status("对话已删除。")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_busy(self, busy: bool) -> None:
        for widget in (
            self.base_url_edit,
            self.model_edit,
            self.api_key_edit,
            self.timeout_spin,
            self.prompt_edit,
            self.session_list,
            self.settings_button,
            self.review_button,
            *self._session_buttons,
        ):
            widget.setEnabled(not busy)
        self.send_button.setEnabled(not busy)

    def _is_current_worker(self, worker) -> bool:
        return worker is None or worker is self._worker

    def send_current_prompt(self) -> None:
        if not self.send_button.isEnabled():
            return
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "缺少内容", "请先输入要发送的内容。")
            return
        self.prompt_edit.clear()
        self._send_prompt(prompt)

    def review_current_workflow(self) -> None:
        if not self.send_button.isEnabled():
            return
        self._send_prompt(REVIEW_WORKFLOW_PROMPT)

    def _send_prompt(self, prompt: str) -> None:
        self._save_provider_from_form()
        self._append_chat_message("user", prompt)
        try:
            messages = build_ai_chat_messages(
                chat_system_prompt(workflow_context=editor_workflow_context(self.main_window)),
                chat_history(self._current_session()),
            )
        except Exception as exc:
            self._set_status(str(exc))
            return
        self._set_status("正在请求 AI 服务…")
        self._set_busy(True)
        self._worker = _AIWorker(self._provider_config(), messages, self)
        self._worker.completed.connect(self._on_reply)
        self._worker.failed.connect(self._on_reply_failed)
        self._worker.finished.connect(self._on_reply_finished)
        self._worker.start()

    def _on_reply_finished(self) -> None:
        if not self._is_current_worker(self.sender()) or not _widget_alive(self):
            return
        self._set_busy(False)

    def _on_reply(self, text: str) -> None:
        if not self._is_current_worker(self.sender()) or not _widget_alive(self):
            return
        self._append_chat_message("assistant", text)
        self._set_status("已回复。")

    def _on_reply_failed(self, message: str) -> None:
        if not self._is_current_worker(self.sender()) or not _widget_alive(self):
            return
        self._append_chat_message("assistant", f"请求失败：{message}")
        self._set_status(f"请求失败：{message}")
