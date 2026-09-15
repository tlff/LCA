# -*- coding: utf-8 -*-
"""变量条件列表编辑器。

弹窗式 UI，每行 (变量名, 运算符, 期望值, 跳转目标卡片ID)。
任意行可 +/- 删除、上下移动；每行变量名独立。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from task_workflow.runtime_store import normalize_var_name

logger = logging.getLogger(__name__)


class VariableConditionEditorDialog(QDialog):
    """多 if 条件列表编辑器。

    入参：
        conditions   - [{'variable_name': str, 'operator': str,
                        'expected': str, 'jump_id': Optional[int]}, ...]
        workflow_cards_info - Dict[seq_id, (task_type, card_id)]，用于填充跳转目标下拉框
        current_card_id - 当前卡片 ID（默认从下拉框里排除自身）
        parent - 父控件

    信号：
        conditions_updated(list) - 用户点"确定"后发出，回传完整列表。
    """

    conditions_updated = Signal(list)

    OPERATORS = ["==", "!=", "包含", "不包含", "为空", "不为空", "长度等于"]
    # 标识"非法变量名"行的背景色
    _INVALID_BG = QColor(255, 220, 220)
    _INVALID_FG = QColor(150, 0, 0)

    def __init__(
        self,
        conditions: List[Dict[str, Any]],
        workflow_cards_info: Optional[Dict[int, Tuple[str, int]]] = None,
        current_card_id: Optional[int] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        # 深拷贝入参
        self._conditions: List[Dict[str, Any]] = []
        for c in (conditions or []):
            if not isinstance(c, dict):
                continue
            self._conditions.append({
                "variable_name": str(c.get("variable_name") or ""),
                "operator": str(c.get("operator") or "=="),
                "expected": str(c.get("expected") or ""),
                "jump_id": c.get("jump_id"),
            })
        self._workflow_cards_info = dict(workflow_cards_info or {})
        self._current_card_id = current_card_id
        self._table: Optional[QTableWidget] = None
        self._summary_label: Optional[QLabel] = None

        self.setWindowTitle("变量条件列表编辑器")
        self.resize(820, 460)
        self._init_ui()
        self._load_rows()
        self._update_summary()

    # ------------------------------------------------------------------ UI
    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 顶部摘要
        self._summary_label = QLabel()
        self._summary_label.setObjectName("variableConditionSummary")
        self._summary_label.setWordWrap(True)
        self._summary_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed,
        )
        layout.addWidget(self._summary_label)

        # 主表格：4 列（变量名 / 运算符 / 期望值 / 跳转目标）
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["变量名", "运算符", "期望值", "跳转目标卡片"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)

        # 工具按钮
        toolbar = QHBoxLayout()
        add_btn = QPushButton("+ 添加条件")
        add_btn.clicked.connect(lambda: self._append_row("", "==", "", None))
        del_btn = QPushButton("- 删除选中")
        del_btn.clicked.connect(self._delete_selected_row)
        up_btn = QPushButton("↑ 上移")
        up_btn.clicked.connect(lambda: self._move_row(-1))
        down_btn = QPushButton("↓ 下移")
        down_btn.clicked.connect(lambda: self._move_row(1))
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_all)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addWidget(up_btn)
        toolbar.addWidget(down_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # 底部按钮（确定 / 取消）
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        button_box.accepted.connect(self._on_ok)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # ------------------------------------------------------------------ 表格行操作
    def _load_rows(self) -> None:
        assert self._table is not None
        for c in self._conditions:
            self._append_row(
                c.get("variable_name", ""),
                c.get("operator", "=="),
                str(c.get("expected", "")),
                c.get("jump_id"),
                skip_summary_update=True,
            )
        self._update_summary()

    def _make_jump_combo(self) -> QComboBox:
        cb = QComboBox()
        cb.addItem("（无跳转）", None)
        for seq_id, info in sorted(self._workflow_cards_info.items()):
            try:
                task_type, card_id = info
            except (TypeError, ValueError):
                continue
            try:
                card_id_int = int(card_id)
            except (TypeError, ValueError):
                continue
            if self._current_card_id is not None and card_id_int == int(self._current_card_id):
                continue
            label = f"{task_type} (ID: {card_id_int})"
            cb.addItem(label, card_id_int)
        return cb

    def _append_row(
        self,
        variable_name: str,
        op: str,
        expected: str,
        jump_id: Optional[int],
        skip_summary_update: bool = False,
    ) -> None:
        assert self._table is not None
        row = self._table.rowCount()
        self._table.insertRow(row)

        # 0: 变量名（QLineEdit）
        name_edit = QLineEdit(str(variable_name))
        name_edit.setPlaceholderText("例如：mode")
        name_edit.textChanged.connect(lambda *_: self._on_var_name_changed(row))
        self._table.setCellWidget(row, 0, name_edit)

        # 1: 运算符
        op_cb = QComboBox()
        op_cb.addItems(self.OPERATORS)
        if op in self.OPERATORS:
            op_cb.setCurrentText(op)
        op_cb.currentIndexChanged.connect(lambda *_: self._update_summary())
        self._table.setCellWidget(row, 1, op_cb)

        # 2: 期望值
        value_item = QTableWidgetItem(str(expected))
        self._table.setItem(row, 2, value_item)

        # 3: 跳转目标
        jb = self._make_jump_combo()
        if jump_id is not None:
            idx = jb.findData(int(jump_id))
            if idx >= 0:
                jb.setCurrentIndex(idx)
        jb.currentIndexChanged.connect(lambda *_: self._update_summary())
        self._table.setCellWidget(row, 3, jb)

        # 立即标色（如果变量名非法）
        self._mark_row_invalid(row)
        if not skip_summary_update:
            self._update_summary()

    def _on_var_name_changed(self, row: int) -> None:
        self._mark_row_invalid(row)
        self._update_summary()

    def _mark_row_invalid(self, row: int) -> None:
        """给变量名非法的行上背景色。"""
        assert self._table is not None
        name_edit = self._table.cellWidget(row, 0)
        if not isinstance(name_edit, QLineEdit):
            return
        text = name_edit.text()
        is_invalid = False
        if text.strip() == "":
            is_invalid = True
        else:
            try:
                normalize_var_name(text)
            except ValueError:
                is_invalid = True
        brush = QBrush(self._INVALID_BG if is_invalid else QColor(Qt.GlobalColor.white))
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item is None:
                # 单元格是 widget 时创建一个空 item 让 setBackground 生效
                item = QTableWidgetItem("")
                self._table.setItem(row, col, item)
            item.setBackground(brush)
            if is_invalid and col == 0:
                item.setForeground(QBrush(self._INVALID_FG))
            else:
                item.setForeground(QBrush(QColor(Qt.GlobalColor.black)))

    def _has_any_invalid(self) -> bool:
        assert self._table is not None
        for r in range(self._table.rowCount()):
            name_edit = self._table.cellWidget(r, 0)
            if not isinstance(name_edit, QLineEdit):
                continue
            text = name_edit.text()
            if not text.strip():
                return True
            try:
                normalize_var_name(text)
            except ValueError:
                return True
        return False

    def _delete_selected_row(self) -> None:
        assert self._table is not None
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选中要删除的一行")
            return
        self._table.removeRow(row)
        self._update_summary()

    def _move_row(self, delta: int) -> None:
        assert self._table is not None
        row = self._table.currentRow()
        if row < 0:
            return
        target = row + delta
        if target < 0 or target >= self._table.rowCount():
            return
        rows_data = [self._collect_row(r) for r in (row, target)]
        self._write_row(target, rows_data[0])
        self._write_row(row, rows_data[1])
        self._table.setCurrentCell(target, 0)
        self._mark_row_invalid(row)
        self._mark_row_invalid(target)
        self._update_summary()

    def _clear_all(self) -> None:
        assert self._table is not None
        if self._table.rowCount() == 0:
            return
        confirm = QMessageBox.question(
            self,
            "确认",
            "确定要清空所有条件吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self._table.setRowCount(0)
            self._update_summary()

    def _collect_row(self, row: int) -> Dict[str, Any]:
        assert self._table is not None
        name_edit = self._table.cellWidget(row, 0)
        var_name = name_edit.text() if isinstance(name_edit, QLineEdit) else ""
        op_cb = self._table.cellWidget(row, 1)
        op = op_cb.currentText() if isinstance(op_cb, QComboBox) else "=="
        value_item = self._table.item(row, 2)
        expected = value_item.text() if value_item else ""
        jb = self._table.cellWidget(row, 3)
        jump_id = jb.currentData() if isinstance(jb, QComboBox) else None
        if jump_id is not None:
            try:
                jump_id = int(jump_id)
            except (TypeError, ValueError):
                jump_id = None
        return {
            "variable_name": str(var_name),
            "operator": op,
            "expected": expected,
            "jump_id": jump_id,
        }

    def _write_row(self, row: int, data: Dict[str, Any]) -> None:
        """覆写指定行（用于移动行）。"""
        assert self._table is not None
        name_edit = self._table.cellWidget(row, 0)
        if isinstance(name_edit, QLineEdit):
            name_edit.setText(str(data.get("variable_name", "")))
        op_cb = self._table.cellWidget(row, 1)
        if isinstance(op_cb, QComboBox):
            op = data.get("operator", "==")
            if op in self.OPERATORS:
                op_cb.setCurrentText(op)
        value_item = self._table.item(row, 2)
        if value_item is not None:
            value_item.setText(str(data.get("expected", "")))
        jb = self._table.cellWidget(row, 3)
        if isinstance(jb, QComboBox):
            target_id = data.get("jump_id")
            if target_id is None:
                jb.setCurrentIndex(0)
            else:
                idx = jb.findData(int(target_id))
                if idx >= 0:
                    jb.setCurrentIndex(idx)

    def _collect_all(self) -> List[Dict[str, Any]]:
        assert self._table is not None
        out: List[Dict[str, Any]] = []
        for r in range(self._table.rowCount()):
            out.append(self._collect_row(r))
        return out

    def _update_summary(self) -> None:
        if self._summary_label is None:
            return
        total = self._table.rowCount() if self._table is not None else 0
        invalid = sum(
            1 for r in range(total)
            if self._cell_var_name(r) and self._is_invalid_var(self._cell_var_name(r))
        ) if total else 0
        if total == 0:
            self._summary_label.setText(
                "暂无条件。点击\"+ 添加条件\"新增一行。"
            )
            return
        # 已配置行数（变量名合法）
        valid = total - invalid
        self._summary_label.setText(
            f"共 {total} 条条件（{valid} 条变量名合法，{invalid} 条非法）。"
            f"按顺序求值，首个命中即生效。"
        )

    def _cell_var_name(self, row: int) -> str:
        w = self._table.cellWidget(row, 0) if self._table else None
        return w.text() if isinstance(w, QLineEdit) else ""

    @staticmethod
    def _is_invalid_var(text: str) -> bool:
        if not text.strip():
            return True
        try:
            normalize_var_name(text)
            return False
        except ValueError:
            return True

    # ------------------------------------------------------------------ OK
    def _on_ok(self) -> None:
        if self._has_any_invalid():
            QMessageBox.warning(
                self,
                "变量名非法",
                "存在变量名为空或不合法（必须以字母/下划线开头，仅含字母数字下划线，"
                "不能以双下划线开头）。请修正后再确定。",
            )
            return
        result = self._collect_all()
        self.conditions_updated.emit(result)
        self.accept()

    # ------------------------------------------------------------------ Public
    def get_conditions(self) -> List[Dict[str, Any]]:
        return self._collect_all()


__all__ = ["VariableConditionEditorDialog"]