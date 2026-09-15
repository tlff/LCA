# -*- coding: utf-8 -*-
"""参数面板 · 变量条件编辑器集成。

提供：
- `_parse_variable_conditions(text)` - 解析 hidden JSON 字符串为条件列表
- `_open_variable_condition_editor()` - 弹出 VariableConditionEditorDialog，
  编辑后回写到 current_parameters['variable_conditions'] 并发参数变更信号
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ParameterPanelVariableConditionMixin:
    """为参数面板注入"变量条件列表"按钮 + 弹窗的集成逻辑。"""

    # 让工厂 mixin 在生成按钮文本时能复用本类方法
    def _parse_variable_conditions(self, raw: Any) -> List[Dict[str, Any]]:
        """从 hidden JSON 字符串解析条件列表。

        每行结构：{'variable_name': str, 'operator': str, 'expected': str, 'jump_id': Optional[int]}
        """
        if raw is None:
            return []
        text = str(raw).strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        cleaned: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            op = str(item.get("operator") or "==").strip() or "=="
            expected = item.get("expected", "")
            if expected is None:
                expected = ""
            jump_id = item.get("jump_id")
            try:
                jump_id_int: Optional[int] = int(jump_id) if jump_id not in (None, "") else None
            except (TypeError, ValueError):
                jump_id_int = None
            cleaned.append({
                "variable_name": str(item.get("variable_name") or ""),
                "operator": op,
                "expected": str(expected),
                "jump_id": jump_id_int,
            })
        return cleaned

    def _open_variable_condition_editor(self) -> None:
        """打开变量条件列表编辑器弹窗。"""
        try:
            raw = self.current_parameters.get("variable_conditions", "") or ""
            conditions = self._parse_variable_conditions(raw)

            workflow_cards_info = getattr(self, "workflow_cards_info", None) or {}
            current_card_id = getattr(self, "current_card_id", None)

            from ui.dialogs.variable_condition_editor_dialog import VariableConditionEditorDialog

            dlg = VariableConditionEditorDialog(
                conditions=conditions,
                workflow_cards_info=workflow_cards_info,
                current_card_id=current_card_id,
                parent=self,
            )

            def _on_updated(new_conditions: List[Dict[str, Any]]) -> None:
                try:
                    json_str = json.dumps(new_conditions, ensure_ascii=False)
                    self.current_parameters["variable_conditions"] = json_str
                    # 更新 hidden 控件文本（如果存在）
                    hidden_widget = self.widgets.get("variable_conditions")
                    if hidden_widget is not None and hasattr(hidden_widget, "setText"):
                        try:
                            hidden_widget.setText(json_str)
                        except Exception:
                            pass
                    # 更新预览 textarea
                    preview_widget = self.widgets.get("conditions_preview")
                    if preview_widget is not None and hasattr(preview_widget, "setPlainText"):
                        preview_text = self._format_variable_conditions_preview(new_conditions)
                        try:
                            preview_widget.setPlainText(preview_text)
                        except Exception:
                            pass
                    # 更新按钮文本
                    for wname, w in self.widgets.items():
                        if not hasattr(w, "setText"):
                            continue
                        pdef = self.param_definitions.get(wname, {})
                        if pdef.get("widget_hint") == "variable_condition_editor":
                            count = len(new_conditions)
                            w.setText(
                                f"编辑条件列表 ({count}条)" if count else "编辑条件列表"
                            )
                    # 发信号让 MainWindow 把更新写回卡片 parameters
                    try:
                        self.parameters_changed.emit(
                            self.current_card_id, self.current_parameters.copy()
                        )
                    except Exception:
                        pass
                    logger.info(
                        "变量条件列表已更新，共 %d 条", len(new_conditions)
                    )
                except Exception as exc:
                    logger.exception("更新变量条件列表失败: %s", exc)

            dlg.conditions_updated.connect(_on_updated)
            dlg.exec()

        except Exception as exc:
            logger.exception("打开变量条件编辑器失败: %s", exc)
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "错误", f"打开变量条件编辑器失败: {exc}")
            except Exception:
                pass

    def _format_variable_conditions_preview(self, conditions: List[Dict[str, Any]]) -> str:
        """格式化预览文本，UI 面板只读展示。"""
        if not conditions:
            return "未配置条件\n\n点击下方\"编辑条件列表\"添加"
        lines: List[str] = []
        for idx, c in enumerate(conditions, start=1):
            var_name = c.get("variable_name", "")
            op = c.get("operator", "==")
            expected = c.get("expected", "")
            jump_id = c.get("jump_id")
            target = f"→ 卡片 {jump_id}" if jump_id is not None else "（无跳转）"
            if op in {"为空", "不为空"}:
                cond_text = f"{var_name} {op}"
            else:
                cond_text = f"{var_name} {op} {expected!r}"
            lines.append(f"{idx}. {cond_text}    {target}")
        return "\n".join(lines)