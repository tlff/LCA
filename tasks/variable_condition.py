# -*- coding: utf-8 -*-
"""变量条件跳转任务模块。

两种用法：

1) **多路 if（推荐）**：参数面板上点"编辑条件列表"按钮，在弹窗里 N 行
   `(运算符, 期望值, 跳转目标卡片ID)`。运行时按顺序求值，首个命中即跳到
   该行指定的 `jump_id`；都不命中走 `on_failure`。

2) **单 if 旧版兼容**：直接填 `variable_name` / `comparison_operator` /
   `expected_value` / `on_success` / `success_jump_target_id` /
   `on_failure` / `failure_jump_target_id`。新工作流建议用方式 1。

参数名复用 4 键 (on_success / *_jump_target_id) 是为了让 UI 端
_JUMP_PARAMETER_KEYS
（ui/workflow_parts/workflow_view_connection_mixin.py:7-10）
自动维护 success / failure 端口连线。
"""

from __future__ import annotations

import json
import logging
import operator
from typing import Any, Callable, Dict, List, Optional, Tuple

from task_workflow.runtime_store import normalize_var_name
from task_workflow.workflow_context import get_runtime_store

logger = logging.getLogger(__name__)

TASK_TYPE = "变量条件跳转"
TASK_NAME = "变量条件跳转"

# --- 比较运算符（字符串语义） ---
COMPARISON_OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "包含": lambda a, b: (b or "") in (a or ""),
    "不包含": lambda a, b: (b or "") not in (a or ""),
    "为空": lambda a, b: not str(a or ""),
    "不为空": lambda a, b: bool(str(a or "")),
    "长度等于": lambda a, b: len(str(a or "")) == int(b) if str(b).lstrip("-").isdigit() else False,
}

COMPARISON_OPERATOR_OPTIONS = list(COMPARISON_OPERATORS.keys())

DEFAULT_COMPARISON_OPERATOR = "=="


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _coerce_text(value: Any) -> str:
    """把任意值转字符串用于'包含/为空/长度等于'等运算。"""
    if value is None:
        return ""
    return str(value)


def _evaluate_comparison(op: str, actual: Any, expected: Any) -> bool:
    """根据 op 计算 actual ? expected，返回 bool。"""
    op_func = COMPARISON_OPERATORS.get(op) or COMPARISON_OPERATORS[DEFAULT_COMPARISON_OPERATOR]
    try:
        if op in {"包含", "不包含"}:
            return bool(op_func(_coerce_text(actual), _coerce_text(expected)))
        if op in {"为空", "不为空"}:
            return bool(op_func(_coerce_text(actual), None))
        if op == "长度等于":
            try:
                length = int(expected)
            except (TypeError, ValueError):
                length = -1
            return bool(op_func(_coerce_text(actual), length))
        if op in {"==", "!="}:
            return bool(op_func(_coerce_text(actual), _coerce_text(expected)))
        return bool(op_func(actual, expected))
    except Exception as exc:
        logger.warning(
            "变量条件跳转比较失败 op=%s actual=%r expected=%r err=%s",
            op, actual, expected, exc,
        )
        return False


def _resolve_jump_id(raw_id: Any) -> Optional[int]:
    """把字符串/None 解析为 int 跳转目标；非法返回 None。"""
    if raw_id is None:
        return None
    text = str(raw_id).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _parse_variable_conditions(raw: Any) -> List[Dict[str, Any]]:
    """解析 variable_conditions 字段为 [{variable_name, operator, expected, jump_id}, ...]。

    容忍：JSON 解析失败、字段不存在、非 list 类型——全部按空列表返回。
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
        op = str(item.get("operator") or DEFAULT_COMPARISON_OPERATOR).strip()
        if op not in COMPARISON_OPERATORS:
            op = DEFAULT_COMPARISON_OPERATOR
        expected = item.get("expected", "")
        if expected is None:
            expected = ""
        cleaned.append({
            "variable_name": str(item.get("variable_name") or ""),
            "operator": op,
            "expected": str(expected),
            "jump_id": _resolve_jump_id(item.get("jump_id")),
        })
    return cleaned


def _format_conditions_preview(conditions: List[Dict[str, Any]]) -> str:
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


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """参数面板定义。"""
    return {
        "---multi_if---": {
            "type": "separator",
            "label": "多路条件列表（推荐）",
        },
        "edit_conditions": {
            "label": "编辑条件列表",
            "type": "button",
            "button_text": "编辑条件列表",
            "widget_hint": "variable_condition_editor",
            "tooltip": "打开弹窗，按顺序添加 N 条 (运算符, 期望值, 跳转目标卡片ID)。",
        },
        "variable_conditions": {
            "type": "hidden",
            "default": "[]",
            "tooltip": "条件列表（JSON 格式，由弹窗编辑）",
        },
        "conditions_preview": {
            "label": "当前条件",
            "type": "textarea",
            "default": "未配置条件\n\n点击下方\"编辑条件列表\"添加",
            "readonly": True,
            "height": 110,
            "tooltip": "显示已配置的条件列表（只读，由弹窗维护）",
        },
        "---legacy_single_if---": {
            "type": "separator",
            "label": "单条件（旧版兼容，仅当上面条件列表为空时生效）",
        },
        "variable_name": {
            "label": "变量名",
            "type": "text",
            "default": "",
            "tooltip": (
                "读取的工作流级变量名。仅当上面\"多路条件列表\"为空时生效；"
                "多路模式下每个条件行自带变量名，这里不起作用。"
            ),
            "placeholder": "例如：retry_count",
        },
        "comparison_operator": {
            "label": "比较方式",
            "type": "select",
            "options": COMPARISON_OPERATOR_OPTIONS,
            "default": DEFAULT_COMPARISON_OPERATOR,
            "tooltip": "如何对比变量值与目标值（仅当多路条件列表为空时生效）。",
        },
        "expected_value": {
            "label": "目标值",
            "type": "text",
            "default": "",
            "tooltip": "用于对比的目标值（字符串）。",
            "placeholder": "例如：1",
            "condition": {
                "param": "comparison_operator",
                "value": ["==", "!=", "包含", "不包含", "长度等于"],
            },
        },
        "missing_value_action": {
            "label": "变量不存在时",
            "type": "select",
            "options": ["视为不满足", "视为满足", "执行下一步", "停止工作流"],
            "default": "视为不满足",
            "tooltip": "当变量未在运行时存储中定义时的兜底行为。",
        },
        # --- 满足时动作 ---
        "---on_success---": {
            "type": "separator",
            "label": "条件满足时",
        },
        "on_success": {
            "label": "动作",
            "type": "select",
            "options": ["执行下一步", "继续执行本步骤", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
        },
        "success_jump_target_id": {
            "label": "跳转目标 ID",
            "type": "int",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"},
        },
        # --- 不满足时动作 ---
        "---on_failure---": {
            "type": "separator",
            "label": "条件不满足时",
        },
        "on_failure": {
            "label": "动作",
            "type": "select",
            "options": ["执行下一步", "继续执行本步骤", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
        },
        "failure_jump_target_id": {
            "label": "跳转目标 ID",
            "type": "int",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"},
        },
    }


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _resolve_action(
    action_text: str,
    *,
    jump_id: Optional[int],
    card_id: Optional[int],
    detail: Optional[str],
) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """把 (action, jump_id, detail) 翻译成标准四元组。"""
    if action_text == "跳转到步骤" and jump_id is not None:
        return True, "跳转到步骤", jump_id, detail
    if action_text == "停止工作流":
        return True, "停止工作流", None, detail
    if action_text == "继续执行本步骤":
        return True, "继续执行本步骤", card_id, detail
    return True, "执行下一步", None, detail


def _resolve_failure_action(
    action_text: str,
    *,
    jump_id: Optional[int],
    card_id: Optional[int],
    detail: Optional[str],
) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """不满足时分支翻译。"""
    if action_text == "跳转到步骤" and jump_id is not None:
        return False, "跳转到步骤", jump_id, detail
    if action_text == "停止工作流":
        return False, "停止工作流", None, detail
    if action_text == "继续执行本步骤":
        return False, "继续执行本步骤", card_id, detail
    return False, "执行下一步", None, detail


def _evaluate_row_condition(
    cond: Dict[str, Any],
    *,
    store: Any,
    missing_action: str,
) -> Optional[bool]:
    """对单行条件求值。返回 True/False 表示命中/不命中，None 表示变量缺失且 missing_action 需要特殊处理。

    调用方在 missing_action='视为不满足'（默认）时把 None 当 False 用；
    在 '视为满足' 时把 None 当 True 用。
    """
    raw_name = cond.get("variable_name", "")
    try:
        name = normalize_var_name(raw_name)
    except ValueError:
        return None  # 变量名非法 → 当作缺失处理

    with store._lock:
        present = name in store._vars
        actual = store._vars.get(name) if present else None

    if not present:
        if missing_action == "视为满足":
            return True
        if missing_action == "执行下一步":
            return None  # 调用方识别为"跳过"
        if missing_action == "停止工作流":
            return None  # 调用方识别为"停止"
        return False  # 视为不满足

    return _evaluate_comparison(cond["operator"], actual, cond["expected"])


# ---------------------------------------------------------------------------
# execute_task
# ---------------------------------------------------------------------------

def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str = "foreground",
    target_hwnd: Optional[int] = None,
    window_region=None,
    card_id: Optional[int] = None,
    **kwargs: Any,
) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """执行条件跳转（多路优先，旧 single-if 兜底）。"""
    on_success = str(params.get("on_success") or "执行下一步")
    success_jump_id = _resolve_jump_id(params.get("success_jump_target_id"))
    on_failure = str(params.get("on_failure") or "执行下一步")
    failure_jump_id = _resolve_jump_id(params.get("failure_jump_target_id"))
    missing_action = str(params.get("missing_value_action") or "视为不满足").strip()

    # 解析运行时 store
    try:
        store = get_runtime_store()
    except Exception as exc:
        logger.exception("[变量条件跳转 card_id=%s] 获取运行时存储失败: %s", card_id, exc)
        return False, "执行下一步", None, f"获取存储失败: {exc}"

    # --- 路径 1：多路条件列表（推荐）---
    conditions = _parse_variable_conditions(params.get("variable_conditions"))
    if conditions:
        # 1) 先做行级变量名校验（空名/非法名都直接失败）
        for idx, cond in enumerate(conditions, start=1):
            raw = cond.get("variable_name", "")
            try:
                normalize_var_name(raw)
            except ValueError:
                logger.warning(
                    "[变量条件跳转 card_id=%s] 第 %d 行变量名非法: %r",
                    card_id, idx, raw,
                )
                return False, "执行下一步", None, f"第 {idx} 行变量名非法: {raw!r}"

        # 2) 顺序求值；变量缺失按 missing_value_action 处理
        for idx, cond in enumerate(conditions, start=1):
            verdict = _evaluate_row_condition(cond, store=store, missing_action=missing_action)
            if verdict is None:
                # 行变量缺失 → 视为不命中（行级兜底），继续评估后续行
                logger.info(
                    "[变量条件跳转 card_id=%s] 第 %d 行变量 %s 缺失，按 missing_value_action=%s 当作不命中",
                    card_id, idx, cond.get("variable_name"), missing_action,
                )
                continue
            if verdict is True:
                row_jump_id = cond["jump_id"]
                logger.info(
                    "[变量条件跳转 card_id=%s] 多路命中 #%d: var=%s op=%s expected=%r -> jump_id=%s",
                    card_id, idx,
                    cond.get("variable_name"),
                    cond["operator"], cond["expected"], row_jump_id,
                )
                if row_jump_id is not None:
                    return True, "跳转到步骤", row_jump_id, None
                # 行无 jump_id：回退到 on_success
                return _resolve_action(
                    on_success,
                    jump_id=success_jump_id,
                    card_id=card_id,
                    detail=None,
                )

        # 都不命中
        logger.info(
            "[变量条件跳转 card_id=%s] 多路条件全部不匹配", card_id,
        )
        return _resolve_failure_action(
            on_failure,
            jump_id=failure_jump_id,
            card_id=card_id,
            detail="条件不满足",
        )

    # --- 路径 2：旧 single-if 兼容 ---
    raw_name = params.get("variable_name", "")
    try:
        name = normalize_var_name(raw_name)
    except ValueError:
        name = None

    if name is None:
        logger.warning("[变量条件跳转 card_id=%s] 非法变量名: %r", card_id, raw_name)
        return False, "执行下一步", None, f"非法变量名: {raw_name!r}"

    op = str(params.get("comparison_operator") or DEFAULT_COMPARISON_OPERATOR).strip()
    if op not in COMPARISON_OPERATORS:
        op = DEFAULT_COMPARISON_OPERATOR
    expected = params.get("expected_value", "")

    with store._lock:
        present = name in store._vars
        actual_value = store._vars.get(name) if present else None

    if not present:
        logger.info(
            "[变量条件跳转 card_id=%s] 旧单条件模式变量 %s 未定义，按 missing_value_action=%s 处理",
            card_id, name, missing_action,
        )
        if missing_action == "视为满足":
            condition_met = True
        elif missing_action == "执行下一步":
            return True, "执行下一步", None
        elif missing_action == "停止工作流":
            return False, "停止工作流", None, f"变量 {name} 未定义"
        else:
            condition_met = False
    else:
        condition_met = _evaluate_comparison(op, actual_value, expected)

    if condition_met:
        logger.info(
            "[变量条件跳转 card_id=%s] 旧条件满足 %s %s %r",
            card_id, name, op, expected,
        )
        return _resolve_action(
            on_success,
            jump_id=success_jump_id,
            card_id=card_id,
            detail=None,
        )
    logger.info(
        "[变量条件跳转 card_id=%s] 旧条件不满足 %s %s %r",
        card_id, name, op, expected,
    )
    return _resolve_failure_action(
        on_failure,
        jump_id=failure_jump_id,
        card_id=card_id,
        detail="条件不满足",
    )