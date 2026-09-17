"""Parameter panel entry that opens the independent AI assistant window."""

from __future__ import annotations

from ..parameter_panel_support import *


class ParameterPanelAIMixin:
    """AI 助手是独立窗口；这里只保留入口和底栏还原。"""

    def show_ai(self, main_window=None) -> None:
        window = main_window or getattr(self, "main_window", None) or getattr(self, "parent_window", None)
        if window is None:
            return
        from ui.dialogs.ai_assistant_dialog import open_ai_assistant_dialog

        if main_window is not None:
            self.main_window = main_window
        open_ai_assistant_dialog(window)

    def _restore_standard_footer_buttons(self) -> None:
        if hasattr(self, "apply_button") and self.apply_button is not None:
            self.apply_button.setText("应用")
            self.apply_button.setEnabled(True)
        if hasattr(self, "reset_button") and self.reset_button is not None:
            self.reset_button.setText("重置")
            self.reset_button.setProperty("class", "")
            self._repolish_panel_button(self.reset_button)

    @staticmethod
    def _repolish_panel_button(button) -> None:
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()
