from ..parameter_panel_support import *


class ParameterPanelWidgetTableSelectorHintConditionsMixin:
    def _create_conditions_table_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        import json as json_module
        from ui.dialogs.conditions_table_dialog import ConditionsTableDialog

        table_widget, summary_label, edit_button, hidden_edit = self._create_table_selector_container(
            '已配置 0 条条件',
            '编辑条件',
        )

        conditions_cache = self._load_conditions_table_value(
            current_value if current_value is not None else param_def.get('default', '[]')
        )
        hidden_edit.setPlainText(json_module.dumps(conditions_cache, ensure_ascii=True))
        self.current_parameters[name] = hidden_edit.toPlainText()
        self._update_conditions_summary(summary_label, len(conditions_cache))

        def _open_conditions_dialog():
            nonlocal conditions_cache
            try:
                card_filter_id = self._get_table_selector_card_filter_id(param_def)
                workflow_filter_id = self._get_table_selector_workflow_filter_id(param_def)
            except (TypeError, ValueError) as exc:
                QMessageBox.warning(self, '条件选择错误', str(exc))
                return
            dialog = ConditionsTableDialog(
                conditions_cache,
                self,
                card_id=card_filter_id,
                workflow_id=workflow_filter_id,
                variable_names=[],
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                conditions_cache = dialog.get_conditions()
                hidden_edit.setPlainText(json_module.dumps(conditions_cache, ensure_ascii=True))
                self.current_parameters[name] = hidden_edit.toPlainText()
                self._update_conditions_summary(summary_label, len(conditions_cache))

        edit_button.clicked.connect(_open_conditions_dialog)
        self._register_widget(name, hidden_edit)
        return table_widget

    @staticmethod
    def _load_conditions_table_value(value) -> list:
        import json as json_module

        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json_module.loads(value)
            except json_module.JSONDecodeError as exc:
                raise ValueError('条件配置必须是有效的 JSON 列表') from exc
            if not isinstance(parsed, list):
                raise ValueError('条件配置必须是 JSON 列表')
            return parsed
        if value in (None, ''):
            return []
        raise TypeError(f'无效的条件配置: {type(value).__name__}')

    @staticmethod
    def _update_conditions_summary(summary_label, count: int):
        summary_label.setText(f'已配置 {count} 条条件')
