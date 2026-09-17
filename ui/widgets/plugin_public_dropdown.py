# -*- coding: utf-8 -*-
"""插件 BindWindowEx 公共属性：一行下拉，弹出层两列多选。弹层外观与 CustomDropdown 相同。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QWidget,
)

from ui.widgets.custom_widgets import DropdownArrowButton, RoundedPopupFrame
from utils.plugin.bind_modes import (
    PLUGIN_PUBLIC_OPTIONS,
    normalize_plugin_public,
    plugin_public_label,
    plugin_public_tooltip,
)
from utils.window.window_activation_utils import show_and_raise_widget


def _theme_color(key: str, default: str) -> str:
    try:
        from themes import get_theme_manager

        return get_theme_manager().get_color(key)
    except Exception:
        return default


class PluginPublicDropdown(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plugin_public_dropdown")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._updating = False
        self._checks: dict[str, QCheckBox] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.display_button = DropdownArrowButton()
        self.display_button.setObjectName("customDropdownButton")
        self.display_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.display_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.display_button.clicked.connect(self._toggle_popup)
        layout.addWidget(self.display_button)

        flags = Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        if hasattr(Qt.WindowType, "NoDropShadowWindowHint"):
            flags |= Qt.WindowType.NoDropShadowWindowHint
        popup_parent = None
        try:
            if parent:
                popup_parent = parent.window()
        except RuntimeError:
            popup_parent = None
        self.popup_frame = RoundedPopupFrame(popup_parent, flags)
        self.popup_frame.setObjectName("customDropdownPopup")
        self.popup_frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.popup_frame.setContentsMargins(0, 0, 0, 0)
        self.popup_frame.hide()

        inner = QWidget(self.popup_frame)
        inner.setObjectName("pluginPublicInner")
        inner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        inner.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        inner.setAutoFillBackground(False)
        grid = QGridLayout(inner)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, token in enumerate(PLUGIN_PUBLIC_OPTIONS):
            box = QCheckBox(plugin_public_label(token), inner)
            box.setObjectName(f"plugin_public_{token.replace('.', '_')}")
            box.setAutoFillBackground(False)
            box.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            box.setToolTip(plugin_public_tooltip(token))
            box.toggled.connect(self._on_toggled)
            grid.addWidget(box, index // 2, index % 2)
            self._checks[token] = box
        self._inner = inner

        self._sync_display()
        self.destroyed.connect(self._cleanup_popup)
        try:
            from themes import get_theme_manager

            self._theme_manager = get_theme_manager()
            self._theme_manager.register_theme_change_callback(self._apply_popup_theme)
        except Exception:
            self._theme_manager = None

    def selected(self) -> list[str]:
        picked = [token for token, box in self._checks.items() if box.isChecked()]
        return list(normalize_plugin_public(picked))

    def set_selected(self, values) -> None:
        wanted = set(normalize_plugin_public(values))
        self._updating = True
        try:
            for token, box in self._checks.items():
                box.setChecked(token in wanted)
        finally:
            self._updating = False
        self._sync_display()

    def _sync_display(self) -> None:
        selected = self.selected()
        if not selected:
            text = "未选择"
        elif len(selected) == 1:
            text = plugin_public_label(selected[0])
        elif len(selected) == 2:
            text = f"{plugin_public_label(selected[0])}、{plugin_public_label(selected[1])}"
        else:
            text = f"已选 {len(selected)} 项"
        self.display_button.setText(text)
        if selected:
            self.setToolTip("、".join(plugin_public_label(token) for token in selected))
        else:
            self.setToolTip("BindWindowEx 公共属性，可多选。未选则不附带 public 参数。")

    def _on_toggled(self, _checked: bool = False) -> None:
        if self._updating:
            return
        self._sync_display()
        self.changed.emit()

    def _toggle_popup(self) -> None:
        if self.popup_frame.isVisible():
            self.popup_frame.hide()
            return
        self._show_popup()

    def _apply_popup_theme(self) -> None:
        card = _theme_color("card", "#ffffff")
        border = _theme_color("border", "#d0d0d0")
        self.popup_frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.popup_frame.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.popup_frame.setAutoFillBackground(False)
        self.popup_frame.setBackgroundColor(card)
        self.popup_frame.setBorderColor(border)
        self.popup_frame.setStyleSheet("")
        self._inner.setAutoFillBackground(False)
        self._inner.setStyleSheet("")

    def _popup_content_size(self, popup_width: int) -> tuple[int, int]:
        grid = self._inner.layout()
        margins = grid.contentsMargins()
        row_count = max(1, grid.rowCount())
        spacing = grid.verticalSpacing()
        if spacing < 0:
            spacing = 6
        row_height = 0
        for box in self._checks.values():
            box.ensurePolished()
            row_height = max(row_height, box.sizeHint().height(), box.minimumSizeHint().height())
        if row_height <= 0:
            row_height = 22
        height = (
            margins.top()
            + margins.bottom()
            + row_height * row_count
            + spacing * (row_count - 1)
            + 8
        )
        grid.activate()
        hinted = self._inner.sizeHint()
        return max(popup_width, hinted.width(), 420), max(height, hinted.height(), 1)

    def _show_popup(self) -> None:
        if not self.isVisible() or not self.isEnabled():
            return
        self._apply_popup_theme()
        button_rect = self.display_button.rect()
        global_pos = self.display_button.mapToGlobal(button_rect.bottomLeft())
        popup_width = max(1, self.display_button.width(), self.width())
        popup_width, popup_height = self._popup_content_size(popup_width)
        self.popup_frame.setFixedSize(popup_width, popup_height)
        self._inner.setGeometry(0, 0, popup_width, popup_height)
        self.popup_frame.move(global_pos)
        show_and_raise_widget(self.popup_frame, log_prefix="自定义下拉弹层")

    def _cleanup_popup(self, *_args) -> None:
        manager = getattr(self, "_theme_manager", None)
        if manager is not None:
            try:
                manager.unregister_theme_change_callback(self._apply_popup_theme)
            except Exception:
                pass
            self._theme_manager = None
        popup = getattr(self, "popup_frame", None)
        if popup is None:
            return
        try:
            popup.hide()
            popup.deleteLater()
        except RuntimeError:
            return
