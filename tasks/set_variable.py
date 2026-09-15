# -*- coding: utf-8 -*-
"""设置变量任务模块。

在工作流中创建/覆盖若干个工作流级变量（持久到 RuntimeStore._vars）。
后续任何节点（包括自定义脚本、条件控制、变量跳转等）都可以读到这些变量。

参数格式（多行文本，每行一个变量）：
    name1=value1
    name2=value2
    # 以 # 开头的行视为注释
    # 空行会被忽略
    # 等号左侧视为变量名，右侧视为变量值（整体按字符串写入）
    # 变量名必须以字母/下划线开头，仅含字母数字下划线，不得以双下划线开头，长度≤64

变量读取方式：
  - 在 "自定义脚本" 节点里：变量.获取("name1")
  - 在其他节点的参数里：{{ vars.name1 }}
  - 在其他任务模块里：RuntimeStore.get_var("name1")（通过 get_runtime_store() 拿 store）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from task_workflow.runtime_store import normalize_var_name
from task_workflow.workflow_context import get_runtime_store

logger = logging.getLogger(__name__)

TASK_TYPE = "设置变量"
TASK_NAME = "设置变量"


def _safe_var_name(name: Any) -> Optional[str]:
    """规范化变量名；非法返回 None。"""
    try:
        return normalize_var_name(name)
    except ValueError:
        return None


def _parse_kv_text(text: Any) -> List[Tuple[str, str]]:
    """解析多行文本为 [(name, value), ...] 列表。

    规则：
      - 忽略空行与以 # 开头的注释行
      - 去掉每行首尾空白
      - 第一个 = 切分（name=value）；没有 = 视为非法（返回时由调用方处理）
      - name 与 value 都 strip
    """
    if text is None:
        return []
    if not isinstance(text, str):
        text = str(text)
    pairs: List[Tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            pairs.append((line, ""))  # 标记为"无等号"
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        pairs.append((name, value))
    return pairs


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """参数面板定义。"""
    return {
        "---variable_setting---": {
            "type": "separator",
            "label": "变量设置",
        },
        "variables_kv": {
            "label": "变量列表",
            "type": "text",
            "default": "",
            "multiline": True,
            "height": 120,
            "tooltip": (
                "每行一个变量，写法：name=value\n"
                "示例：\n"
                "  mode=fast\n"
                "  retry_count=3\n"
                "  timeout=5000\n"
                "以 # 开头的行视为注释；空行会被忽略。\n"
                "变量名必须以字母/下划线开头，仅含字母数字下划线，"
                "长度不超过 64，且不能以双下划线开头。"
            ),
            "placeholder": "name1=value1\nname2=value2",
        },
        "---post_exec---": {
            "type": "separator",
            "label": "执行后操作",
        },
        "on_failure": {
            "label": "设置失败时",
            "type": "select",
            "options": ["执行下一步", "继续执行本步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "当任一变量名非法或写入失败时执行的动作。",
        },
    }


def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str = "foreground",
    target_hwnd: Optional[int] = None,
    window_region=None,
    card_id: Optional[int] = None,
    **kwargs: Any,
) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """设置一个或多个工作流级变量。

    返回四元组 (success, action, jump_id, detail)；本节点无跳转语义，
    action 固定为 "执行下一步"，jump_id 为 None。
    """
    raw_text = params.get("variables_kv", "")
    on_failure = str(params.get("on_failure") or "执行下一步")

    pairs = _parse_kv_text(raw_text)
    if not pairs:
        logger.info("[设置变量 card_id=%s] 变量列表为空，跳过写入", card_id)
        return True, "执行下一步", None

    # 第一遍：校验所有变量名（任一非法即失败）
    normalized: List[Tuple[str, str]] = []
    bad_lines: List[str] = []
    for raw_name, value in pairs:
        if not raw_name:
            bad_lines.append("(空变量名)")
            continue
        if "=" not in raw_name and value == "" and "=" not in raw_name:
            # _parse_kv_text 标记的"无等号"行
            bad_lines.append(repr(raw_name))
            continue
        name = _safe_var_name(raw_name)
        if name is None:
            bad_lines.append(repr(raw_name))
            continue
        normalized.append((name, value))

    if bad_lines:
        detail = f"非法变量名: {', '.join(bad_lines)}"
        logger.warning("[设置变量 card_id=%s] %s", card_id, detail)
        if on_failure == "停止工作流":
            return False, "停止工作流", None, detail
        if on_failure == "继续执行本步骤":
            return False, "继续执行本步骤", card_id, detail
        return False, "执行下一步", None, detail

    try:
        store = get_runtime_store()
    except Exception as exc:  # 防御性兜底
        logger.exception("[设置变量 card_id=%s] 获取运行时存储失败: %s", card_id, exc)
        return False, "执行下一步", None, f"获取存储失败: {exc}"

    written: List[str] = []
    for name, value in normalized:
        try:
            stored = store.set_var(name, value)
        except Exception as exc:
            logger.exception("[设置变量 card_id=%s] 写入 %s 失败: %s", card_id, name, exc)
            return False, "执行下一步", None, f"写入 {name} 失败: {exc}"
        written.append(f"{name}={stored!r}")

    logger.info(
        "[设置变量 card_id=%s] 写入 %d 个变量: %s",
        card_id, len(written), "; ".join(written),
    )
    return True, "执行下一步", None