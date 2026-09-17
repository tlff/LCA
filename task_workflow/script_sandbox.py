# -*- coding: utf-8 -*-
"""受控自定义脚本：中文命令调用现有能力，禁止 import 和直接读写文件。"""

from __future__ import annotations

import ast
import io
import logging
import math
import random
import threading
import tokenize
import time
import json
import os
import platform
import sys
from typing import Any, Dict, Optional, Tuple

from task_workflow.runtime_store import RuntimeStore, _json_safe, normalize_var_name
from task_workflow.script_commands import RESULT_FIELD_ALIASES, CommandHost, ScriptResult

logger = logging.getLogger(__name__)


def _as_bool(value: Any) -> bool:
    """Normalize Chinese/boolean script values for sandbox APIs."""
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"", "0", "false", "no", "否", "假", "关闭", "隐藏"}:
            return False
        if text in {"1", "true", "yes", "是", "真", "开启", "显示"}:
            return True
    return bool(value)

def _runtime_limit(name: str, default: float) -> float:
    """Read script limits from environment; 0 means unlimited for trusted use."""
    try:
        value = float(os.getenv(name, str(default)))
        return max(0.0, value)
    except (TypeError, ValueError):
        return float(default)


MAX_SOURCE_CHARS = int(_runtime_limit("LCA_SCRIPT_MAX_SOURCE_CHARS", 20000))

COMMAND_NAMES = (
    "找图",
    "找色",
    "找所有图",
    "等图",
    "等色",
    "等文字",
    "等图消失",
    "等色消失",
    "等文字消失",
    "等检测",
    "等检测消失",
    "持续检测",
    "停止检测",
    "持续找图",
    "停止找图",
    "多线程",
    "关闭线程",
    "线程状态",
    "等待线程",
    "线程结果",
    "框内点",
    "随机点",
    "距离",
    "角度",
    "取色",
    "比色",
    "点击",
    "按下",
    "松开",
    "按住",
    "连点",
    "移动",
    "相对移动",
    "鼠标位置",
    "拖拽",
    "滚轮",
    "按键",
    "输入",
    "延时",
    "等毫秒",
    "找字",
    "找字库",
    "等字库",
    "等字库消失",
    "点字库",
    "点文字",
    "点元素",
    "检测",
    "播放",
    "停止播放",
    "回放",
    "暂停回放",
    "继续回放",
    "停止回放",
    "截图",
    "等按键",
    "记录",
    "成功",
    "失败",
)
_BUILTIN_CALLS = (
    "长度",
    "整数",
    "小数",
    "到文本",
    "真假",
    "最小",
    "最大",
    "绝对值",
    "开方",
    "平方根",
    "正弦",
    "余弦",
    "限制",
    "范围",
    "随机",
    "包含",
    "截取",
    "替换",
    "分割",
    "去空格",
    "查找",
    "提取数字",
    "时间",
    "枚举",
    "配对",
    "排序",
    "四舍五入",
    "全部",
    "任一",
    "字典获取",
    "字典设置",
    "列表追加",
    "列表弹出",
    "类型",
    "断言",
    "字典键",
    "字典值",
    "列表合并",
    "开头是",
    "结尾是",
    "JSON解析",
    "JSON生成",
)

# These names are used only as the internal targets of Chinese-name
# translation. They are not accepted as script source identifiers.
_TRANSLATED_BUILTIN_CALLS = (
    "len",
    "int",
    "float",
    "str",
    "bool",
    "min",
    "max",
    "abs",
    "range",
)
_REMOVED_ENGLISH_BUILTINS = frozenset(
    {
        *_TRANSLATED_BUILTIN_CALLS,
        "enumerate",
        "zip",
        "sorted",
        "round",
        "all",
        "any",
        "list",
        "tuple",
        "dict",
        "set",
        "sum",
        "reversed",
    }
)

_RESULT_METHODS = frozenset({"点", "随机点"})
_EXCEPTION_NAMES = (
    "Exception",
    "BaseException",
    "ValueError",
    "TypeError",
    "RuntimeError",
    "KeyError",
    "IndexError",
    "AttributeError",
    "ZeroDivisionError",
    "StopIteration",
    "NameError",
    "ArithmeticError",
    "AssertionError",
)

ALLOWED_CALLS = {
    "大漠内存.模块基址", "大漠内存.模块大小",
    "大漠内存.读取整数", "大漠内存.读取单精度", "大漠内存.读取双精度",
    "大漠内存.读取文本", "大漠内存.读取数据",
    "大漠内存.写入整数", "大漠内存.写入单精度", "大漠内存.写入双精度",
    "大漠内存.写入文本", "大漠内存.写入数据",
    "大漠内存.搜索整数", "大漠内存.搜索单精度", "大漠内存.搜索双精度",
    "大漠内存.搜索文本", "大漠内存.搜索数据",
    "大漠内存.申请", "大漠内存.释放", "大漠内存.清理",
    "大漠汇编.添加", "大漠汇编.清空", "大漠汇编.调用",
    "大漠汇编.基址调用", "大漠汇编.超时",
    "变量.获取",
    "变量.设置",
    "变量.增加",
    "变量.存在",
    "变量.删除",
    "变量.全局获取",
    "变量.全局设置",
    "变量.全局增加",
    "变量.全局存在",
    "变量.全局删除",
    "区域.设置",
    "区域.获取",
    "区域.存在",
    "区域.删除",
    "区域.列表",
    "剪贴板.获取",
    "剪贴板.设置",
    "窗口.设置分辨率",
    "窗口.枚举",
    "窗口.查找",
    "窗口.信息",
    "窗口.激活",
    "窗口.查找元素",
    "窗口.元素文本",
    "窗口.设置元素值",
    "窗口.元素属性",
    "窗口.元素聚焦",
    "窗口.元素切换",
    "窗口.元素选择",
    "窗口.元素展开",
    "窗口.元素折叠",
    "窗口.坐标转换",
    "窗口.兼容性",
    "输入设备.枚举",
    "输入设备.能力",
    "输入设备.状态",
    "输入设备.等待按钮",
    "输入设备.HID枚举",
    "输入设备.HID读取",
    "输入设备.HID写入",
    "窗口.子窗口",
    "窗口.消息",
    "窗口.Z序",
    "窗口.DPI",
    "网络.请求",
    "事件.等待窗口",
    "事件.等待进程",
    "事件.等待窗口关闭",
    "事件.等待进程退出",
    "事件.等待文件",
    "窗口.关闭",
    "窗口.显示",
    "窗口.隐藏",
    "窗口.最小化",
    "窗口.还原",
    "窗口.移动",
    "窗口.大小",
    "进程.查找",
    "进程.信息",
    "进程.是否运行",
    "进程.启动",
    "进程.关闭",
    "热键.注册",
    "热键.注销",
    "热键.全部注销",
    "定时器.启动",
    "定时器.停止",
    "组件.加载",
    "组件.调用",
    "组件.读取",
    "组件.写入",
    "组件.运行",
    "组件.关闭",
    "数据.读取",
    "数据.写入",
    "数据.JSON读取",
    "数据.JSON写入",
    "数据.INI读取",
    "数据.INI写入",
    "数据.CSV读取",
    "数据.SQLite查询",
    "性能.快照",
    "数据.存在",
    "数据.删除",
    *COMMAND_NAMES,
    *_BUILTIN_CALLS,
    *_TRANSLATED_BUILTIN_CALLS,
    *_EXCEPTION_NAMES,
}

ALLOWED_CALL_ROOTS = frozenset({*COMMAND_NAMES, *_BUILTIN_CALLS, *_TRANSLATED_BUILTIN_CALLS, *_EXCEPTION_NAMES})

_CN_IDENT_MAP = {
    "否则如果": "elif",
    "如果": "if",
    "否则": "else",
    "循环": "for",
    "当": "while",
    "范围": "range",
    "中断": "break",
    "继续": "continue",
    "并且": "and",
    "或者": "or",
    "在": "in",
    "真": "True",
    "假": "False",
    "空": "None",
    "略过": "pass",
    "返回": "return",
    "子程序": "def",
    "函数": "def",
    "长度": "len",
    "整数": "int",
    "小数": "float",
    "到文本": "str",
    "真假": "bool",
    "最小": "min",
    "最大": "max",
    "绝对值": "abs",
}

_FORBIDDEN_NODE_CN = {
    "Import": "导入",
    "ImportFrom": "导入",
    "AsyncFunctionDef": "异步函数",
    "ClassDef": "类定义",
    "With": "with 语句",
    "AsyncWith": "异步 with",
    "Lambda": "匿名函数",
    "Await": "await",
    "Yield": "yield",
    "YieldFrom": "yield from",
    "Global": "global",
    "Nonlocal": "nonlocal",
    "Delete": "删除",
    "AnnAssign": "类型注解",
    "NamedExpr": "海象运算符",
    "GeneratorExp": "生成器表达式",
}
_FORBIDDEN_ATTRS = frozenset(
    {
        "gi_frame",
        "gi_code",
        "gi_running",
        "gi_yieldfrom",
        "f_back",
        "f_builtins",
        "f_globals",
        "f_locals",
        "f_code",
        "f_trace",
        "f_lasti",
        "f_lineno",
        "cr_frame",
        "cr_code",
        "cr_await",
        "cr_running",
        "cr_origin",
        "tb_frame",
        "tb_next",
        "tb_lasti",
        "tb_lineno",
        "co_code",
        "co_consts",
        "co_names",
        "co_varnames",
        "func_globals",
        "func_code",
    }
)

_SYNTAX_CN = (
    ("'break' outside loop", "中断 只能写在循环里"),
    ("'continue' not properly in loop", "继续 只能写在循环里"),
    ("expected ':'", "这里少了冒号"),
    ("invalid syntax", "写法不对"),
    ("unexpected EOF while parsing", "代码没写完"),
    ("unexpected EOF", "代码没写完"),
    ("unmatched ')'", "括号不配对"),
    ("unmatched ']'", "括号不配对"),
    ("unmatched '}'", "括号不配对"),
    ("EOL while scanning string literal", "字符串没写完"),
    ("unterminated string literal", "字符串没写完"),
    ("cannot assign to", "这个名字不能当变量用"),
    ("'return' outside function", "不能单独写返回，请用 成功() 或 失败()"),
)
FIELD_ALIASES = RESULT_FIELD_ALIASES

ALLOWED_NODES = (
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Del,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.Attribute,
    ast.Call,
    ast.keyword,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Try,
    ast.ExceptHandler,
    ast.Raise,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.comprehension,
    ast.IfExp,
)


class ScriptError(ValueError):
    """脚本语法或运行错误。"""

    def __init__(self, message: str, lineno: Optional[int] = None):
        text = str(message or "")
        line = int(lineno) if lineno else None
        if line and "第" not in text[:8]:
            text = f"第{line}行：{text}"
        super().__init__(text)
        self.lineno = line


class ScriptOutcome(Exception):
    def __init__(self, success: bool, detail: str = ""):
        self.success = bool(success)
        self.detail = str(detail or "")
        super().__init__(self.detail)


class _Guard:
    def __init__(
        self,
        stop_checker=None,
        pause_checker=None,
    ) -> None:
        self.stop_checker = stop_checker
        self.pause_checker = pause_checker

    def __call__(self) -> None:
        self._check_stop()
        self._wait_pause()

    def loop(self) -> None:
        self()

    def _check_stop(self) -> None:
        if not callable(self.stop_checker):
            return
        try:
            stopped = bool(self.stop_checker())
        except ScriptError:
            raise
        except Exception as exc:
            raise ScriptError(f"停止检查失败: {exc}") from exc
        if stopped:
            raise ScriptError("已停止")

    def _wait_pause(self) -> None:
        if not callable(self.pause_checker):
            return
        while True:
            try:
                paused = bool(self.pause_checker())
            except ScriptError:
                raise
            except Exception as exc:
                raise ScriptError(f"暂停检查失败: {exc}") from exc
            if not paused:
                return
            self._check_stop()
            time.sleep(0.05)


def _is_outcome_call(stmt: ast.AST) -> str:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return ""
    func = stmt.value.func
    if isinstance(func, ast.Name) and func.id in {"成功", "失败"}:
        return func.id
    return ""


def _is_exit_stmt(stmt: ast.AST) -> str:
    name = _is_outcome_call(stmt)
    if name:
        return f"{name}()"
    if isinstance(stmt, ast.Return):
        return "返回"
    return ""


def _is_ident_char(char: str) -> bool:
    return bool(char) and (char.isalnum() or char == "_" or "\u4e00" <= char <= "\u9fff")


def _peek_ident(text: str, index: int) -> str:
    cursor = index
    length = len(text)
    while cursor < length and text[cursor] in {" ", "\t"}:
        cursor += 1
    if cursor >= length or not _is_ident_char(text[cursor]):
        return ""
    end = cursor + 1
    while end < length and _is_ident_char(text[end]):
        end += 1
    return text[cursor:end]


_CN_PUNCT_MAP = {
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "［": "[",
    "］": "]",
    "｛": "{",
    "｝": "}",
    "，": ",",
    "、": ",",
    "：": ":",
    "；": ";",
    "。": ".",
    "！": "!",
    "？": "?",
    "＝": "=",
    "＋": "+",
    "－": "-",
    "×": "*",
    "÷": "/",
    "／": "/",
    "＊": "*",
    "＜": "<",
    "＞": ">",
    "％": "%",
    "＆": "&",
    "｜": "|",
    "～": "~",
    "＠": "@",
    "＃": "#",
    "＾": "^",
    "｀": "`",
    "＄": "$",
    "　": " ",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "〝": '"',
    "〞": '"',
    "「": '"',
    "」": '"',
    "『": '"',
    "』": '"',
    "＂": '"',
    "‘": "'",
    "’": "'",
    "‛": "'",
    "＇": "'",
}


def map_script_punct_char(char: str) -> str:
    return _CN_PUNCT_MAP.get(char, char)


def string_open_quote(line: str, column: int) -> Optional[str]:
    """返回光标处所在字符串的开引号（半角 ``"`` 或 ``'``），注释里返回 ``"#"``，
    不在字符串/注释里返回 ``None``。

    与 ``normalize_script_punctuation`` 对齐：全角引号按其映射的半角引号开/闭
    字符串（例如 ``“`` 开、``”`` 闭），这样编辑器判断“光标是否在字符串里”与
    半角化逻辑保持一致。
    """
    text = str(line or "")
    limit = max(0, min(int(column), len(text)))
    quote: Optional[str] = None  # 已开字符串的半角引号
    escape = False
    index = 0
    while index < limit:
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif map_script_punct_char(char) == quote:
                quote = None
            index += 1
            continue
        if char == "#":
            return "#"
        mapped = map_script_punct_char(char)
        if mapped in {'"', "'"}:
            quote = mapped
        index += 1
    return quote


def cursor_in_string_or_comment(line: str, column: int) -> bool:
    return string_open_quote(line, column) is not None


_QUOTE_CHARS = frozenset(char for char, mapped in _CN_PUNCT_MAP.items() if mapped in {'"', "'"}) | {'"', "'"}


def normalize_script_punctuation(source: str) -> str:
    """把代码里的中文/全角标点换成英文标点；字符串和注释里的内容原样保留。

    用户要输入/记录的文本（"你好，世界。"）不能被改成半角，否则打进游戏里的字都变了。
    中文引号“ ”「 」可以用来开闭字符串，配对的那个也会被换成英文引号。
    """
    text = str(source or "")
    out: list[str] = []
    quote: Optional[str] = None
    escape = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if quote is not None:
            if escape:
                escape = False
                out.append(char)
            elif char == "\\":
                escape = True
                out.append(char)
            elif quote == '"""' or quote == "'''":
                if text.startswith(quote, index):
                    out.append(quote)
                    index += 3
                    quote = None
                    continue
                out.append(char)
            elif char in _QUOTE_CHARS and map_script_punct_char(char) == quote:
                out.append(quote)
                quote = None
            else:
                out.append(char)
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            if newline < 0:
                out.append(text[index:])
                break
            out.append(text[index:newline])
            index = newline
            continue
        if text.startswith('"""', index) or text.startswith("'''", index):
            quote = text[index : index + 3]
            out.append(quote)
            index += 3
            continue
        mapped = map_script_punct_char(char)
        if mapped in {'"', "'"}:
            quote = mapped
        out.append(mapped)
        index += 1
    return "".join(out)


def translate_cn_script(source: str) -> str:
    """把中文关键字/内置名译成 Python，字符串和注释里不改；英文内置由校验阶段拒绝。"""
    text = normalize_script_punctuation(str(source or ""))
    out: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if text.startswith('"""', index) or text.startswith("'''", index):
            quote = text[index : index + 3]
            cursor = index + 3
            while cursor < length:
                if text.startswith(quote, cursor):
                    cursor += 3
                    break
                if text[cursor] == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                cursor += 1
            out.append(text[index:cursor])
            index = cursor
            continue
        if char in {'"', "'"}:
            cursor = index + 1
            while cursor < length:
                if text[cursor] == "\\":
                    cursor += 2
                    continue
                if text[cursor] == char:
                    cursor += 1
                    break
                cursor += 1
            out.append(text[index:cursor])
            index = cursor
            continue
        if char == "#":
            newline = text.find("\n", index)
            if newline < 0:
                out.append(text[index:])
                break
            out.append(text[index:newline])
            index = newline
            continue
        if _is_ident_char(char):
            cursor = index + 1
            while cursor < length and _is_ident_char(text[cursor]):
                cursor += 1
            ident = text[index:cursor]
            nxt = _peek_ident(text, cursor)
            if ident == "是":
                out.append("is" if nxt in {"空", "None"} else "==")
            elif ident == "不是":
                out.append("is not" if nxt in {"空", "None"} else "not")
            else:
                out.append(_CN_IDENT_MAP.get(ident, ident))
            index = cursor
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _syntax_error_text(exc: SyntaxError) -> str:
    message = str(exc.msg or "写法不对")
    for english, chinese in _SYNTAX_CN:
        if english in message:
            return chinese
    return message


def parse_script(source: str) -> ast.AST:
    return ast.parse(translate_cn_script(str(source or "")))


_PLACEHOLDER_NAMES = frozenset(
    {
        "条件",
        "次数",
        "图片",
        "模型",
        "文件",
        "等待",
        "颜色",
        "文本",
        "目标",
        "名称",
        "说明",
        "内容",
        "编号",
        "进程号",
        "程序",
        "标题",
        "类名",
        "宽",
        "高",
        "x",
        "y",
        "自动化ID",
        "名字",
        "值",
        "默认值",
        "秒",
        "动作",
        "按键",
        "步数",
        "步长",
        "类别",
        "横向",
        "纵向",
        "边距",
        "自己",
        "点1",
        "点2",
        "名字",
        "角度",
        "下限",
        "上限",
        "对象",
        "值1",
        "值2",
        "起点",
        "终点",
        "宽",
        "高",
        "双击",
        "偏移横坐标",
        "偏移纵坐标",
        "偏移x",
        "偏移y",
        "随机",
        "随机横坐标",
        "随机纵坐标",
        "随机x",
        "随机y",
        "区域",
        "大漠内存",
        "大漠汇编",
        "键",
        "阈值",
        "策略",
        "方向",
        "超时",
        "间隔",
        "偏色",
        "最多",
        "毫秒",
        "片段",
        "旧",
        "新",
        "分隔符",
        "字数",
        "横坐标",
        "纵坐标",
        "起点横坐标",
        "起点纵坐标",
        "终点横坐标",
        "终点纵坐标",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
    }
)
_PLACEHOLDER_HINTS = {
    "文件": "用资源栏导入，或写成 \"提示.wav\"",
    "等待": "写成 真 或 假。真是播完再往下，假是接着跑",
    "图片": "用工具栏「截图」选图，或写成 \"确定.png\"",
    "图片2": "第二张图。多张图并行识别，按顺序取第一张命中，阈值仍写 阈值=",
    "模型": "写成 onnx 路径，例如 \"yolo/xxx.onnx\"",
    "颜色": "用「取色」，或写成 \"255,0,0\"",
    "目标": "写成 图，或 \"确定\"",
    "条件": "插入找图/检测，或写成 图",
    "文本": "写成要输入的文字，例如 \"你好\"",
    "内容": "写成要记录的内容",
    "说明": "写成失败原因，例如 \"没找到\"",
    "名称": "写成控件名，或用「拾取元素」",
    "秒": "写成等待秒数，例如 0.3；随机时长写成 (0.2, 0.6)",
    "连发": "写成 真 或 假。真是按住时继续出字，假是只按住不连发",
    "动作": "写成 \"按下\" 或 \"松开\"",
    "按键": "写成 \"Ctrl+C\" 或 \"Enter\"",
    "次数": "写成数字，或 变量.获取(\"次数\", 3)",
    "名字": "写成变量名，例如 \"次数\"",
    "编号": "写成卡片 ID，例如 3",
    "类别": "写成这个模型里的类别名，例如 \"敌人\"。不写就认全部类",
    "横向": "写成 0 到 1，0 是左边、1 是右边",
    "纵向": "写成 0 到 1，0 是顶、1 是底。脚下常用 0.85",
    "边距": "写成离边多少像素，例如 2",
    "自己": "写成你赋过值的检测结果，例如 自己",
    "点1": "写成一个检测结果，或四个数字 距离(x1, y1, x2, y2) / 角度(x1, y1, x2, y2)",
    "点2": "写成另一个检测结果或坐标点",
    "角度": "写成度数，例如 角度(自己, 目标)",
    "下限": "写成最小允许值",
    "上限": "写成最大允许值",
    "策略": "写成 \"最近\"、\"最大\" 或 \"置信度最高\"",
    "对象": "写成要测量的值，例如 文字.内容",
    "值1": "写成数字或变量",
    "值2": "写成数字或变量",
    "起点": "写成起始数字",
    "终点": "写成结束数字",
    "宽": "写成宽度数字",
    "高": "写成高度数字",
    "双击": "写成 真 或 假",
    "偏移横坐标": "写成像素，正数向右",
    "偏移纵坐标": "写成像素，正数向下",
    "偏移x": "写成像素，正数向右",
    "偏移y": "写成像素，正数向下",
    "随机": "写成随机半径，例如 5。和偏移一起写时先固定偏移再抖",
    "区域": "用工具栏「框选区域」写入 区域.设置，或写成 (横坐标, 纵坐标, 宽, 高) / 区域名",
    "键": "写成 \"左键\" 或 \"右键\"",
    "阈值": "写成 0 到 1 的小数，例如 0.8",
    "方向": "写成 \"向下\" 或 \"向上\"",
    "随机横坐标": "写成 X 随机范围，例如 5",
    "随机纵坐标": "写成 Y 随机范围，例如 5",
    "横坐标": "用「取坐标」，或写成数字",
    "纵坐标": "用「取坐标」，或写成数字",
    "起点横坐标": "用「取坐标」，或写成数字",
    "起点纵坐标": "用「取坐标」，或写成数字",
    "终点横坐标": "用「取坐标」，或写成数字",
    "终点纵坐标": "用「取坐标」，或写成数字",
    "x": "用「取坐标」，或写成数字",
    "y": "用「取坐标」，或写成数字",
    "x1": "用「取坐标」，或写成数字",
    "y1": "用「取坐标」，或写成数字",
    "x2": "用「取坐标」，或写成数字",
    "y2": "用「取坐标」，或写成数字",
}


def unfilled_placeholder_names(source: str) -> list:
    try:
        tree = parse_script(source)
    except SyntaxError:
        return []
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assigned.add(node.id)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)
        if isinstance(node, ast.FunctionDef):
            assigned.add(node.name)
            for arg in list(node.args.args) + list(getattr(node.args, "posonlyargs", []) or []) + list(node.args.kwonlyargs):
                assigned.add(arg.arg)
    call_funcs = set()
    attr_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            call_funcs.add(id(node.func))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            attr_roots.add(id(node.value))
    found = []
    seen = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if id(node) in call_funcs or id(node) in attr_roots:
            continue
        if node.id in assigned or node.id not in _PLACEHOLDER_NAMES or node.id in seen:
            continue
        seen.add(node.id)
        found.append(node.id)
    return found


def unfilled_placeholder_error(source: str) -> str:
    names = unfilled_placeholder_names(source)
    if not names:
        return ""
    name = names[0]
    hint = _PLACEHOLDER_HINTS.get(name, "把占位名改成实际值")
    extra = f"；还有 {'、'.join(names[1:])}" if len(names) > 1 else ""
    return f"还没填写参数：{name}{extra}。{hint}"


_RESERVED_VAR_NAMES = ("当", "在", "是", "真", "假", "空", "子程序", "函数")


def _reserved_name_warnings(source: str) -> list:
    import re

    found = []
    text = str(source or "")
    for name in _RESERVED_VAR_NAMES:
        if re.search(rf"(?<![\w\u4e00-\u9fff]){re.escape(name)}\s*=", text):
            found.append(f"不要用「{name}」当变量名")
    return found


def script_warnings(source: str) -> list:
    found: list = list(_reserved_name_warnings(source))
    try:
        tree = parse_script(source)
    except SyntaxError:
        return found
    placeholder = unfilled_placeholder_error(source)
    if placeholder:
        found.append(placeholder)

    def scan(body: list) -> None:
        for index, stmt in enumerate(body):
            name = _is_exit_stmt(stmt)
            if name:
                rest = [item for item in body[index + 1 :] if not isinstance(item, ast.Pass)]
                if rest:
                    found.append(f"第{stmt.lineno}行：{name} 后面的命令不会执行")
            if isinstance(stmt, ast.FunctionDef):
                scan(stmt.body)
                continue
            if isinstance(stmt, ast.Try):
                scan(stmt.body)
                scan(stmt.orelse)
                scan(stmt.finalbody)
                for handler in stmt.handlers:
                    scan(handler.body)
                continue
            if isinstance(stmt, (ast.If, ast.For, ast.While)):
                if isinstance(stmt, (ast.For, ast.While)):
                    _warn_loop_outcomes(stmt.body, found)
                scan(stmt.body)
                scan(stmt.orelse)

    scan(tree.body)
    return found


def _warn_loop_outcomes(body: list, found: list) -> None:
    for stmt in body:
        name = _is_outcome_call(stmt)
        if name:
            found.append(f"第{stmt.lineno}行：{name}() 写在循环里会立刻结束整段脚本，剩下的轮次不会跑")
            continue
        if isinstance(stmt, ast.If):
            _warn_loop_outcomes(stmt.body, found)
            _warn_loop_outcomes(stmt.orelse, found)


class _ForCountWrap(ast.NodeTransformer):
    """`循环 i 在 6:` 这种次数写法译成 `for i in 6` 后补成可迭代的次数。"""

    def visit_For(self, node):
        self.generic_visit(node)
        node.iter = ast.Call(
            func=ast.Name(id="__iter_count", ctx=ast.Load()),
            args=[node.iter],
            keywords=[],
        )
        ast.copy_location(node.iter, node)
        ast.fix_missing_locations(node.iter)
        return node


class _GuardInsert(ast.NodeTransformer):
    def visit(self, node):
        node = super().visit(node)
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            guard_call = ast.Expr(
                value=ast.Call(func=ast.Name(id="__guard", ctx=ast.Load()), args=[], keywords=[])
            )
            ast.copy_location(guard_call, node)
            return [guard_call, node]
        return node

    def visit_For(self, node):
        self.generic_visit(node)
        node.body = [self._loop_guard(node), *(node.body or [ast.Pass()])]
        return node

    def visit_While(self, node):
        self.generic_visit(node)
        node.body = [self._loop_guard(node), *(node.body or [ast.Pass()])]
        return node

    def _loop_guard(self, node):
        stmt = ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="__guard", ctx=ast.Load()),
                    attr="loop",
                    ctx=ast.Load(),
                ),
                args=[],
                keywords=[],
            )
        )
        ast.copy_location(stmt, node)
        ast.fix_missing_locations(stmt)
        return stmt


def _region_payload(name: str, rect: Tuple[int, int, int, int], ok: bool = True) -> Dict[str, Any]:
    left, top, width, height = rect
    return {
        "ok": ok,
        "kind": "region",
        "name": name,
        "x": left,
        "y": top,
        "width": width,
        "height": height,
        "x1": left,
        "y1": top,
        "x2": left + width,
        "y2": top + height,
    }


class _RegionApi:
    def __init__(self, host: CommandHost) -> None:
        self._host = host

    def 设置(self, 名字: Any, x: Any = None, y: Any = None, 宽: Any = None, 高: Any = None) -> ScriptResult:
        from task_workflow.script_commands import _as_region

        name = str(名字 if 名字 is not None else "").strip()
        if not name:
            raise ValueError("区域名不能为空")
        if isinstance(x, (tuple, list)) and y is None and 宽 is None and 高 is None:
            rect = _as_region(x)
        else:
            rect = _as_region((x, y, 宽, 高))
        if rect is None:
            raise ValueError("区域.设置要写名字和 (x, y, 宽, 高)")
        with self._host._regions_lock:
            self._host._regions[name] = rect
        return ScriptResult(_region_payload(name, rect))

    def 获取(self, 名字: Any) -> ScriptResult:
        name = str(名字 if 名字 is not None else "").strip()
        with self._host._regions_lock:
            rect = self._host._regions.get(name) if name else None
        if rect is None:
            return ScriptResult({"ok": False, "kind": "region", "name": name})
        return ScriptResult(_region_payload(name, rect))

    def 存在(self, 名字: Any) -> bool:
        name = str(名字 if 名字 is not None else "").strip()
        if not name:
            return False
        with self._host._regions_lock:
            return name in self._host._regions

    def 删除(self, 名字: Any) -> bool:
        name = str(名字 if 名字 is not None else "").strip()
        if not name:
            return False
        with self._host._regions_lock:
            return self._host._regions.pop(name, None) is not None

    def 列表(self) -> ScriptResult:
        with self._host._regions_lock:
            items = [_region_payload(name, rect) for name, rect in self._host._regions.items()]
        return ScriptResult({"ok": True, "kind": "region", "items": items})


class _VarsApi:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store
        self._vars: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def 获取(self, 名字: Any, 默认值: Any = None) -> Any:
        key = normalize_var_name(名字)
        with self._lock:
            return self._vars.get(key, 默认值)

    def 设置(self, 名字: Any, 值: Any) -> Any:
        key = normalize_var_name(名字)
        stored = _json_safe(值)
        with self._lock:
            self._vars[key] = stored
        return stored

    def 增加(self, 名字: Any, 步长: Any = 1) -> Any:
        key = normalize_var_name(名字)
        try:
            delta = float(步长)
        except (TypeError, ValueError):
            raise ValueError("步长必须是数字") from None
        with self._lock:
            current = self._vars.get(key, 0)
            try:
                next_value = float(current) + delta
            except (TypeError, ValueError):
                next_value = delta
            if float(next_value).is_integer():
                next_value = int(next_value)
            self._vars[key] = next_value
            return next_value

    def 存在(self, 名字: Any) -> bool:
        key = normalize_var_name(名字)
        with self._lock:
            return key in self._vars

    def 删除(self, 名字: Any) -> bool:
        key = normalize_var_name(名字)
        missing = object()
        with self._lock:
            return self._vars.pop(key, missing) is not missing

    def 全局获取(self, 名字: Any, 默认值: Any = None) -> Any:
        return self._store.get_var(名字, 默认值)

    def 全局设置(self, 名字: Any, 值: Any) -> Any:
        return self._store.set_var(名字, 值)

    def 全局增加(self, 名字: Any, 步长: Any = 1) -> Any:
        return self._store.inc_var(名字, 步长)

    def 全局存在(self, 名字: Any) -> bool:
        return self._store.has_var(名字)

    def 全局删除(self, 名字: Any) -> bool:
        return self._store.delete_var(名字)


class _StoreView:
    def __init__(self, store: RuntimeStore, kind: Optional[str] = None) -> None:
        self._store = store
        self._kind = kind

    def __bool__(self) -> bool:
        return bool(self._store.last(self._kind).get("ok"))

    def __getattr__(self, name: str) -> Any:
        return _AttrView(self._store.last(self._kind)).__getattr__(name)

    def __getitem__(self, key: Any) -> Any:
        return _AttrView(self._store.last(self._kind)).__getitem__(key)


class _AttrView:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise ScriptError("禁止访问该属性")
        key = FIELD_ALIASES.get(name, name)
        if isinstance(self._payload, dict) and key in self._payload:
            return _wrap(self._payload[key])
        raise ScriptError(f"没有字段: {name}")

    def __getitem__(self, key: Any) -> Any:
        if isinstance(self._payload, dict):
            return _wrap(self._payload[key])
        if isinstance(self._payload, list):
            return _wrap(self._payload[int(key)])
        raise ScriptError("该值不支持下标")


class _CardView:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def __getitem__(self, card_id: Any) -> _AttrView:
        return _AttrView(self._store.card_result(card_id))


class _CallableLast:
    def __init__(self, callback, store: RuntimeStore, kind: str, host: Any = None) -> None:
        self._callback = callback
        self._store = store
        self._kind = kind
        self._host = host

    def __call__(self, *args, **kwargs):
        return self._callback(*args, **kwargs)

    def _payload(self) -> Dict[str, Any]:
        if self._host is not None:
            latest = self._host.latest(self._kind)
            if latest is not None:
                return latest
        return self._store.last(self._kind)

    def _result(self) -> ScriptResult:
        return ScriptResult(self._payload())

    def __bool__(self) -> bool:
        return bool(self._payload().get("ok"))

    def __len__(self) -> int:
        return len(self._result())

    def __iter__(self):
        return iter(self._result())

    def __getitem__(self, key: Any) -> Any:
        return self._result()[key]

    def __getattr__(self, name: str) -> Any:
        if name in _RESULT_METHODS:
            return getattr(self._result(), name)
        return _AttrView(self._payload()).__getattr__(name)


def _wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return ScriptResult(value)
    return value


class _CommandSlot:
    """命令可调用；同名赋值只记住结果，不把命令冲掉。"""

    def __init__(self, callback: Any) -> None:
        self._callback = callback
        self._bound = None

    def bind(self, value: Any) -> None:
        self._bound = value

    def __call__(self, *args, **kwargs):
        result = self._callback(*args, **kwargs)
        self._bound = result
        return result

    def __bool__(self) -> bool:
        if self._bound is not None:
            return bool(self._bound)
        callback = self._callback
        try:
            return bool(callback)
        except Exception:
            return True

    def _value_for_container(self) -> Any:
        if self._bound is None:
            raise ScriptError("请先调用命令并保存结果，再读取长度、项目或字段")
        return self._bound

    def __len__(self) -> int:
        return len(self._value_for_container())

    def __iter__(self):
        return iter(self._value_for_container())

    def __getitem__(self, key: Any) -> Any:
        return self._value_for_container()[key]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if self._bound is not None:
            return getattr(self._bound, name)
        callback = self._callback
        try:
            return getattr(callback, name)
        except AttributeError:
            raise ScriptError(f"没有字段: {name}") from None


class _ScriptNamespace(dict):
    def __setitem__(self, key, value):
        current = dict.get(self, key)
        if isinstance(current, _CommandSlot):
            current.bind(value)
            return
        if key in _PROTECTED_ASSIGN_NAMES:
            raise ScriptError(f"不能给命令名赋值：{key}")
        dict.__setitem__(self, key, value)

    def install_command(self, name: str, callback: Any) -> None:
        dict.__setitem__(self, name, callback if isinstance(callback, _CommandSlot) else _CommandSlot(callback))


def _reject_removed_english_builtins(source: str) -> None:
    """Reject removed English builtin names before Chinese translation hides them."""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(str(source or "")).readline)
        for token in tokens:
            if token.type == tokenize.NAME and token.string in _REMOVED_ENGLISH_BUILTINS:
                raise ScriptError(
                    f"英文内置已移除：{token.string}，请使用中文内置或中文编程工具",
                    lineno=token.start[0],
                )
    except (tokenize.TokenError, IndentationError):
        # Syntax validation below produces the canonical script error.
        return


def validate_script(source: str) -> None:
    text = str(source or "")
    if MAX_SOURCE_CHARS > 0 and len(text) > MAX_SOURCE_CHARS:
        raise ScriptError("内容过长")
    _reject_removed_english_builtins(text)
    try:
        tree = parse_script(text)
    except SyntaxError as exc:
        raise ScriptError(f"语法错误: {_syntax_error_text(exc)}", lineno=getattr(exc, "lineno", None)) from exc
    user_funcs = set()
    returns_in_func = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            user_funcs.add(node.name)
            if node.name in _PROTECTED_FUNC_NAMES:
                raise ScriptError(f"不能用命令名定义子程序：{node.name}", lineno=getattr(node, "lineno", None))
            for child in ast.walk(node):
                if isinstance(child, ast.Return):
                    returns_in_func.add(id(child))
    protected_assigns = _PROTECTED_ASSIGN_NAMES | user_funcs
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            name = type(node).__name__
            raise ScriptError(f"不允许使用 {_FORBIDDEN_NODE_CN.get(name, name)}", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Return) and id(node) not in returns_in_func:
            raise ScriptError("不能单独写返回，请用 成功() 或 失败()", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Name) and "__" in node.id:
            raise ScriptError("禁止使用双下划线名称", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Attribute):
            if "__" in node.attr:
                raise ScriptError("禁止访问双下划线属性", lineno=getattr(node, "lineno", None))
            if node.attr in _FORBIDDEN_ATTRS:
                raise ScriptError("禁止访问该属性", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Call):
            path = _call_path(node.func)
            method = path.split(".")[-1] if path else ""
            if (
                path not in ALLOWED_CALLS
                and path.split(".")[0] not in ALLOWED_CALL_ROOTS
                and path not in user_funcs
                and method not in _RESULT_METHODS
            ):
                raise ScriptError(f"不允许调用: {path or type(node.func).__name__}", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _assigned_names(target):
                    if name in protected_assigns:
                        raise ScriptError(f"不能给命令名赋值：{_display_ident(name)}", lineno=getattr(node, "lineno", None))
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id in protected_assigns:
                raise ScriptError(f"不能给命令名赋值：{_display_ident(node.target.id)}", lineno=getattr(node, "lineno", None))


def _display_ident(name: str) -> str:
    """校验发生在中文关键字译成 Python 之后；报错时把中文名一并带上，例如 range（范围）。"""
    for chinese, english in _CN_IDENT_MAP.items():
        if english == name and chinese != name:
            return f"{name}（{chinese}）"
    return name


# 内置函数、异常名不能被当变量覆盖。命令名例外：`找字 = 找字(目标=...)` 是刻意支持的写法，
# 命名空间里的 _CommandSlot 会在同名赋值后仍保持可调用。
_PROTECTED_ASSIGN_NAMES = frozenset(
    {
        *_BUILTIN_CALLS,
        *_TRANSLATED_BUILTIN_CALLS,
        *_EXCEPTION_NAMES,
        "True",
        "False",
        "None",
        "__guard",
        "数据",
        "变量",
        "剪贴板",
        "窗口",
        "组件",
        "网络",
        "性能",
        "区域",
    }
)
_PROTECTED_FUNC_NAMES = frozenset({*COMMAND_NAMES, *_PROTECTED_ASSIGN_NAMES})


def _assigned_names(target: ast.AST) -> list:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for item in target.elts:
            names.extend(_assigned_names(item))
        return names
    return []


def _attr_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attr_path(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _call_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _attr_path(node)
    return ""


def _script_lineno(exc: BaseException) -> Optional[int]:
    line = getattr(exc, "lineno", None)
    try:
        if line:
            return int(line)
    except Exception:
        line = None
    tb = getattr(exc, "__traceback__", None)
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<script>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return int(line) if line else None


def _raise_script_error(message: str, exc: Optional[BaseException] = None) -> None:
    raise ScriptError(message, lineno=_script_lineno(exc) if exc is not None else None) from exc


def _is_int_range_bound(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("+", "-")):
            text = text[1:]
        return bool(text) and text.isdigit()
    return False


def script_for_iterable(value: Any) -> Any:
    """数字当循环次数；其它值保持原样交给 for。"""
    if isinstance(value, bool):
        raise ValueError("循环次数不能是真假")
    if isinstance(value, range):
        return value
    if _is_int_range_bound(value):
        count = int(value) if not isinstance(value, str) else int(str(value).strip())
        if count < 0:
            raise ValueError("循环次数不能是负数")
        return range(count)
    return value


def script_random(*args: Any, 起点: Any = None, 终点: Any = None) -> Any:
    if 起点 is not None or 终点 is not None:
        args = tuple(item for item in (起点, 终点) if item is not None)
    if not args:
        return random.random()
    if len(args) == 1:
        return random.randint(0, max(0, int(args[0]) - 1)) if int(args[0]) > 0 else 0
    low, high = args[0], args[1]
    if _is_int_range_bound(low) and _is_int_range_bound(high):
        start, end = int(low), int(high)
        if end < start:
            start, end = end, start
        return random.randint(start, end)
    start, end = float(low), float(high)
    if end < start:
        start, end = end, start
    return random.uniform(start, end)


def script_sqrt(值: Any) -> float:
    number = float(值)
    if number < 0:
        raise ValueError("开方不能是负数")
    return number ** 0.5


def script_sin(角度: Any) -> float:
    return math.sin(math.radians(float(角度)))


def script_cos(角度: Any) -> float:
    return math.cos(math.radians(float(角度)))


def script_clamp(值: Any, 下限: Any, 上限: Any) -> float:
    number = float(值)
    low = float(下限)
    high = float(上限)
    if low > high:
        low, high = high, low
    return min(high, max(low, number))


def script_contains(文本: Any, 片段: Any) -> bool:
    return str(片段 or "") in str(文本 or "")


def script_slice(文本: Any, 起点: Any, 字数: Any = None) -> str:
    source = str(文本 or "")
    begin = max(0, int(起点 or 1) - 1)
    if 字数 is None or 字数 == "":
        return source[begin:]
    return source[begin : begin + max(0, int(字数))]


def script_replace(文本: Any, 旧: Any, 新: Any, 次数: Any = None) -> str:
    source = str(文本 or "")
    if 次数 is None or 次数 == "":
        return source.replace(str(旧 or ""), str(新 or ""))
    return source.replace(str(旧 or ""), str(新 or ""), int(次数))


def script_strip(文本: Any) -> str:
    return str(文本 or "").strip()


def script_find(文本: Any, 片段: Any) -> int:
    index = str(文本 or "").find(str(片段 or ""))
    return 0 if index < 0 else index + 1


def script_extract_number(文本: Any) -> Any:
    import re

    match = re.search(r"-?\d+(?:\.\d+)?", str(文本 or ""))
    if not match:
        return 0
    raw = match.group(0)
    return float(raw) if "." in raw else int(raw)


def script_split(文本: Any, 分隔符: Any = None) -> list:
    source = str(文本 or "")
    if 分隔符 is None or 分隔符 == "":
        return source.split()
    return source.split(str(分隔符))


def script_now_ms() -> int:
    return int(time.monotonic() * 1000)


def script_json_parse(文本: Any) -> Any:
    try:
        return json.loads(str(文本 or ""))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON解析失败: {exc}") from exc


def script_json_dump(对象: Any) -> str:
    try:
        return json.dumps(对象, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"JSON生成失败: {exc}") from exc


def script_dict_get(字典: Any, 键: Any, 默认值: Any = None) -> Any:
    return 字典.get(键, 默认值) if isinstance(字典, dict) else 默认值


def script_dict_set(字典: Any, 键: Any, 值: Any) -> Any:
    if not isinstance(字典, dict):
        raise TypeError("字典设置的目标必须是字典")
    字典[键] = 值
    return 字典


def script_list_append(列表: Any, 值: Any) -> int:
    if not isinstance(列表, list):
        raise TypeError("列表追加的目标必须是列表")
    列表.append(值)
    return len(列表)


def script_list_pop(列表: Any, 索引: Any = -1) -> Any:
    if not isinstance(列表, list):
        raise TypeError("列表弹出的目标必须是列表")
    return 列表.pop(int(索引))


def script_type(值: Any) -> str:
    return type(值).__name__


def script_assert(条件: Any, 错误信息: Any = "断言失败") -> bool:
    if not 条件:
        raise AssertionError(str(错误信息))
    return True


def script_dict_keys(字典: Any) -> list:
    return list(字典.keys()) if isinstance(字典, dict) else []


def script_dict_values(字典: Any) -> list:
    return list(字典.values()) if isinstance(字典, dict) else []


def script_list_extend(列表: Any, 数据: Any) -> int:
    if not isinstance(列表, list):
        raise TypeError("列表合并的目标必须是列表")
    if not isinstance(数据, (list, tuple, set)):
        raise TypeError("列表合并的数据必须是列表")
    列表.extend(数据)
    return len(列表)


def script_startswith(文本: Any, 前缀: Any) -> bool:
    return str(文本 or "").startswith(str(前缀 or ""))


def script_endswith(文本: Any, 后缀: Any) -> bool:
    return str(文本 or "").endswith(str(后缀 or ""))


def script_sort(列表: Any, 反向: Any = False) -> list:
    if not isinstance(列表, (list, tuple, set)):
        raise TypeError("排序的目标必须是列表")
    return sorted(列表, reverse=bool(反向))


def script_round(数值: Any, 位数: Any = 0) -> Any:
    return round(float(数值), int(位数))


def clipboard_get() -> str:
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            return str(app.clipboard().text() or "")
    except Exception:
        pass
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or "")
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ""
    return ""


def clipboard_set(text: Any) -> str:
    value = str(text or "")
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(value)
            return value
    except Exception:
        pass
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(value)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as exc:
        raise ScriptError(f"剪贴板写入失败: {exc}") from exc
    return value


class _DmMemoryView:
    def __init__(self, host: CommandHost) -> None: self._host = host
    def 模块基址(self, 模块): return self._host.大漠内存_模块基址(模块)
    def 模块大小(self, 模块): return self._host.大漠内存_模块大小(模块)
    def 读取整数(self, 地址, 类型=0): return self._host.大漠内存_读取整数(地址, 类型)
    def 读取单精度(self, 地址): return self._host.大漠内存_读取单精度(地址)
    def 读取双精度(self, 地址): return self._host.大漠内存_读取双精度(地址)
    def 读取文本(self, 地址, 类型, 长度): return self._host.大漠内存_读取文本(地址, 类型, 长度)
    def 读取数据(self, 地址, 长度): return self._host.大漠内存_读取数据(地址, 长度)
    def 写入整数(self, 地址, 类型, 值): return self._host.大漠内存_写入整数(地址, 类型, 值)
    def 写入单精度(self, 地址, 值): return self._host.大漠内存_写入单精度(地址, 值)
    def 写入双精度(self, 地址, 值): return self._host.大漠内存_写入双精度(地址, 值)
    def 写入文本(self, 地址, 类型, 值): return self._host.大漠内存_写入文本(地址, 类型, 值)
    def 写入数据(self, 地址, 数据): return self._host.大漠内存_写入数据(地址, 数据)
    def 搜索整数(self, 范围, 最小值, 最大值, 类型=0): return self._host.大漠内存_搜索整数(范围, 最小值, 最大值, 类型)
    def 搜索单精度(self, 范围, 最小值, 最大值): return self._host.大漠内存_搜索单精度(范围, 最小值, 最大值)
    def 搜索双精度(self, 范围, 最小值, 最大值): return self._host.大漠内存_搜索双精度(范围, 最小值, 最大值)
    def 搜索文本(self, 范围, 文本, 类型): return self._host.大漠内存_搜索文本(范围, 文本, 类型)
    def 搜索数据(self, 范围, 数据): return self._host.大漠内存_搜索数据(范围, 数据)
    def 申请(self, 地址, 大小, 类型): return self._host.大漠内存_申请(地址, 大小, 类型)
    def 释放(self, 地址): return self._host.大漠内存_释放(地址)
    def 清理(self): return self._host.大漠内存_清理()


class _DmAsmView:
    def __init__(self, host: CommandHost) -> None: self._host = host
    def 添加(self, 指令): return self._host.大漠汇编_添加(指令)
    def 清空(self): return self._host.大漠汇编_清空()
    def 调用(self, 模式): return self._host.大漠汇编_调用(模式)
    def 基址调用(self, 模式, 基址): return self._host.大漠汇编_基址调用(模式, 基址)
    def 超时(self, 毫秒, 参数): return self._host.大漠汇编_超时(毫秒, 参数)


class _PerformanceView:
    """Read-only process/runtime metrics for long-running scripts."""

    def __init__(self, host) -> None:
        self._host = host

    def 快照(self) -> ScriptResult:
        payload: Dict[str, Any] = {
            "ok": True,
            "kind": "performance",
            "platform": os.name,
            "python": platform.python_version(),
        }
        try:
            import psutil

            process = psutil.Process(os.getpid())
            memory = process.memory_info()
            payload.update(
                {
                    "available": True,
                    "pid": int(process.pid),
                    "rss_bytes": int(memory.rss),
                    "rss_mb": round(float(memory.rss) / (1024 * 1024), 3),
                    "cpu_percent": float(process.cpu_percent(interval=0.0)),
                    "threads": int(process.num_threads()),
                }
            )
        except Exception as exc:
            payload.update({"ok": False, "available": False, "error": str(exc)})
        try:
            user_threads = getattr(self._host, "_user_threads", {}) or {}
            watch_threads = getattr(self._host, "_watch_threads", {}) or {}
            payload["script_threads"] = sum(1 for thread in user_threads.values() if thread and thread.is_alive())
            payload["watch_threads"] = sum(1 for thread in watch_threads.values() if thread and thread.is_alive())
        except Exception:
            payload["script_threads"] = 0
            payload["watch_threads"] = 0
        try:
            from services.screenshot_pool import get_screenshot_stats, get_screenshot_worker_limit

            payload["screenshot_workers"] = get_screenshot_stats()
            payload["screenshot_worker_limit"] = int(get_screenshot_worker_limit())
        except Exception as exc:
            payload["screenshot_workers"] = {"available": False, "error": str(exc)}
        return ScriptResult(payload)


class _DataApi:
    """脚本专属数据目录：只允许访问应用用户目录下的相对文件。"""

    _MAX_BYTES = 2 * 1024 * 1024

    def _path(self, name: Any) -> str:
        from utils.app_paths import get_user_data_dir

        raw = str(name or "").replace("\\", "/").strip()
        if not raw or raw.startswith("/") or ":" in raw:
            raise ValueError("数据文件名必须是相对路径")
        parts = [part for part in raw.split("/") if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise ValueError("数据文件不能访问上级目录")
        root = os.path.realpath(os.path.join(get_user_data_dir("LCA"), "script_data"))
        path = os.path.realpath(os.path.join(root, *parts))
        if not path.casefold().startswith(root.casefold() + os.sep):
            raise ValueError("数据文件路径越界")
        return path

    def 读取(self, 文件名: Any, 默认值: Any = "") -> str:
        path = self._path(文件名)
        try:
            with open(path, "rb") as handle:
                content = handle.read(self._MAX_BYTES + 1)
            if len(content) > self._MAX_BYTES:
                raise ValueError("数据文件过大")
            return content.decode("utf-8")
        except FileNotFoundError:
            return str(默认值 or "")

    def 写入(self, 文件名: Any, 内容: Any) -> str:
        path = self._path(文件名)
        text = str(内容 if 内容 is not None else "")
        if len(text.encode("utf-8")) > self._MAX_BYTES:
            raise ValueError("数据文件过大")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import tempfile

        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as handle:
                temporary = handle.name
                handle.write(text)
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)
        return text

    def JSON读取(self, 文件名: Any, 默认值: Any = None) -> Any:
        text = self.读取(文件名, "")
        if not text.strip():
            return 默认值
        return script_json_parse(text)

    def JSON写入(self, 文件名: Any, 对象: Any) -> str:
        return self.写入(文件名, script_json_dump(对象))

    def INI读取(self, 文件名: Any, 节: Any, 键: Any, 默认值: Any = "") -> str:
        import configparser
        parser = configparser.ConfigParser()
        path = self._path(文件名)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                parser.read_file(handle)
        except FileNotFoundError:
            return str(默认值 or "")
        return parser.get(str(节), str(键), fallback=str(默认值 or ""))

    def INI写入(self, 文件名: Any, 节: Any, 键: Any, 值: Any) -> str:
        import configparser
        parser = configparser.ConfigParser()
        path = self._path(文件名)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                parser.read_file(handle)
        section, key = str(节).strip(), str(键).strip()
        if not section or not key:
            raise ValueError("INI 节和键不能为空")
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, key, str(值 if 值 is not None else ""))
        from io import StringIO
        output = StringIO()
        parser.write(output)
        return self.写入(文件名, output.getvalue())

    def CSV读取(self, 文件名: Any, 标题行: Any = True, 最多: Any = 10000) -> list:
        import csv
        path = self._path(文件名)
        limit = max(1, min(100000, int(最多)))
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                if _as_bool(标题行):
                    rows = list(csv.DictReader(handle))
                else:
                    rows = [list(row) for row in csv.reader(handle)]
        except FileNotFoundError:
            return []
        if len(rows) > limit:
            raise ValueError("CSV 行数超过限制")
        return rows

    def SQLite查询(self, 文件名: Any, SQL: Any, 参数: Any = (), 最多: Any = 10000) -> list:
        import sqlite3
        statement = str(SQL or "").strip()
        if not statement or not statement.casefold().startswith(("select", "pragma", "with")):
            raise ValueError("SQLite 只允许 SELECT、PRAGMA 或 WITH 查询")
        values = tuple(参数) if isinstance(参数, (list, tuple)) else (() if 参数 is None else (参数,))
        limit = max(1, min(100000, int(最多)))
        path = self._path(文件名)
        try:
            uri = f"file:{path.replace(chr(92), '/') }?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as conn:
                conn.execute("PRAGMA query_only=ON")
                cursor = conn.execute(statement, values)
                columns = [item[0] for item in cursor.description or ()]
                rows = [dict(zip(columns, row)) for row in cursor.fetchmany(limit + 1)]
        except sqlite3.Error as exc:
            raise ValueError(f"SQLite 查询失败: {exc}") from exc
        if len(rows) > limit:
            raise ValueError("SQLite 结果行数超过限制")
        return rows

    def 存在(self, 文件名: Any) -> bool:
        return os.path.isfile(self._path(文件名))

    def 删除(self, 文件名: Any) -> bool:
        try:
            os.remove(self._path(文件名))
            return True
        except FileNotFoundError:
            return False


class _InputDeviceView:
    """受控只读游戏杆状态接口（WinMM）；无设备或非 Windows 返回空结果。"""

    _JOY_RETURNALL = 0xFF
    _JOYERR_NOERROR = 0

    def __init__(self, host=None):
        self._host = host

    def _winmm(self):
        import ctypes
        if os.name != "nt":
            return None
        try:
            dll = ctypes.windll.winmm
            dll.joyGetNumDevs.restype = ctypes.c_uint
            try:
                dll.joyGetPosEx.argtypes = [ctypes.c_uint, ctypes.c_void_p]
                dll.joyGetPosEx.restype = ctypes.c_uint
            except Exception:
                pass
            return dll
        except Exception:
            return None

    @staticmethod
    def _joy_info_type():
        import ctypes
        class JoyInfoEx(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                ("dwXpos", ctypes.c_uint32), ("dwYpos", ctypes.c_uint32), ("dwZpos", ctypes.c_uint32),
                ("dwRpos", ctypes.c_uint32), ("dwUpos", ctypes.c_uint32), ("dwVpos", ctypes.c_uint32),
                ("dwButtons", ctypes.c_uint32), ("dwButtonNumber", ctypes.c_uint32),
                ("dwPOV", ctypes.c_uint32), ("dwReserved1", ctypes.c_uint32), ("dwReserved2", ctypes.c_uint32),
            ]
        return JoyInfoEx

    def _read(self, dll, index: int):
        import ctypes
        info = self._joy_info_type()()
        info.dwSize = ctypes.sizeof(info)
        info.dwFlags = self._JOY_RETURNALL
        try:
            code = int(dll.joyGetPosEx(index, ctypes.byref(info)))
        except Exception as exc:
            return None, str(exc)
        return (info if code == self._JOYERR_NOERROR else None), ("" if code == self._JOYERR_NOERROR else f"winmm:{code}")

    @staticmethod
    def _index(value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("输入设备编号必须是整数")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("输入设备编号必须是整数") from exc
        if not number.is_integer():
            raise ValueError("输入设备编号必须是整数")
        index = int(number)
        if index < 0 or index >= 16:
            raise ValueError("输入设备编号必须在 0 到 15 之间")
        return index

    def 枚举(self) -> list:
        dll = self._winmm()
        if dll is None:
            return []
        result = []
        for index in range(min(16, int(dll.joyGetNumDevs() or 0))):
            info, _ = self._read(dll, index)
            if info is not None:
                result.append({"id": index, "name": f"joystick{index}", "buttons": int(info.dwButtons), "pov": int(info.dwPOV), "x": int(info.dwXpos), "y": int(info.dwYpos), "z": int(info.dwZpos), "connected": True})
        return result

    def 能力(self) -> ScriptResult:
        """Report installed device protocols without probing or injecting input."""
        winmm_available = self._winmm() is not None
        hid_available = self._hid() is not None
        try:
            import vgamepad  # type: ignore
            virtual_gamepad_available = True
        except Exception:
            virtual_gamepad_available = False
        return ScriptResult({
            "ok": True,
            "kind": "input_device_capabilities",
            "winmm": bool(winmm_available),
            "hidapi": bool(hid_available),
            "virtual_gamepad": bool(virtual_gamepad_available),
            "can_read_joystick": bool(winmm_available),
            "can_read_hid": bool(hid_available),
            "can_inject": False,
        })

    @staticmethod
    def _hid():
        try:
            import hid
            return hid
        except Exception:
            return None

    def HID枚举(self) -> ScriptResult:
        hid = self._hid()
        if hid is None:
            return ScriptResult({"ok": False, "kind": "hid", "available": False, "devices": [], "error": "hidapi 未安装"})
        try:
            raw = hid.enumerate()
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "hid", "available": True, "devices": [], "error": str(exc)})
        devices = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            devices.append({key: item.get(key) for key in ("path", "vendor_id", "product_id", "serial_number", "manufacturer_string", "product_string", "usage_page", "usage")})
        return ScriptResult({"ok": True, "kind": "hid", "available": True, "devices": devices})

    def HID读取(self, 路径: Any, 长度: Any = 64, 超时: Any = 1000) -> ScriptResult:
        hid = self._hid()
        if hid is None:
            return ScriptResult({"ok": False, "kind": "hid_read", "available": False, "data": [], "error": "hidapi 未安装"})
        path = 路径
        if not path:
            raise ValueError("HID 路径不能为空")
        try:
            length = int(长度)
            timeout = int(超时)
        except (TypeError, ValueError) as exc:
            raise ValueError("HID 长度和超时必须是整数") from exc
        if length < 1 or length > 4096:
            raise ValueError("HID 长度必须在 1 到 4096 之间")
        if timeout < 0 or timeout > 60000:
            raise ValueError("HID 超时必须在 0 到 60000 毫秒之间")
        device = None
        try:
            device = hid.device()
            device.open_path(path)
            data = list(device.read(length, timeout))
            return ScriptResult({"ok": bool(data), "kind": "hid_read", "available": True, "data": data, "bytes": len(data)})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "hid_read", "available": True, "data": [], "error": str(exc)})
        finally:
            if device is not None:
                try: device.close()
                except Exception: pass

    def HID写入(self, 路径: Any, 数据: Any, 超时: Any = 1000) -> ScriptResult:
        if self._host is None or not bool(self._host.context.get("allow_external_components", False)):
            raise ScriptError("HID 写入需要启用并信任外部组件")
        hid = self._hid()
        if hid is None:
            return ScriptResult({"ok": False, "kind": "hid_write", "available": False, "bytes": 0, "error": "hidapi 未安装"})
        path = 路径
        if not path:
            raise ValueError("HID 路径不能为空")
        if isinstance(数据, (bytes, bytearray)):
            payload = bytes(数据)
        elif isinstance(数据, (list, tuple)):
            try: payload = bytes(int(item) & 0xFF for item in 数据)
            except (TypeError, ValueError) as exc: raise ValueError("HID 数据必须是字节列表") from exc
        else:
            raise TypeError("HID 数据必须是字节列表")
        if not payload or len(payload) > 4096:
            raise ValueError("HID 数据长度必须在 1 到 4096 字节之间")
        try: timeout_ms = int(超时)
        except (TypeError, ValueError) as exc: raise ValueError("HID 超时必须是整数") from exc
        if timeout_ms < 0 or timeout_ms > 60000:
            raise ValueError("HID 超时必须在 0 到 60000 毫秒之间")
        device = None
        try:
            device = hid.device(); device.open_path(path)
            written = int(device.write(payload))
            return ScriptResult({"ok": written == len(payload), "kind": "hid_write", "available": True, "bytes": written})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "hid_write", "available": True, "bytes": 0, "error": str(exc)})
        finally:
            if device is not None:
                try: device.close()
                except Exception: pass

    def 状态(self, 设备: Any = 0) -> ScriptResult:
        dll = self._winmm()
        index = self._index(设备)
        if dll is None:
            return ScriptResult({"ok": False, "kind": "joystick", "id": index, "connected": False})
        info, error = self._read(dll, index)
        if info is None:
            return ScriptResult({"ok": False, "kind": "joystick", "id": index, "connected": False, "error": error})
        return ScriptResult({"ok": True, "kind": "joystick", "id": index, "connected": True, "x": int(info.dwXpos), "y": int(info.dwYpos), "z": int(info.dwZpos), "buttons": int(info.dwButtons), "pov": int(info.dwPOV)})

    def 等待按钮(self, 按钮: Any, 设备: Any = 0, 按下: Any = True, 超时: Any = 30, 间隔: Any = 0.05) -> ScriptResult:
        if isinstance(按钮, bool):
            raise ValueError("手柄按钮必须是整数编号（从 1 开始）")
        try:
            button_value = float(按钮)
        except (TypeError, ValueError) as exc:
            raise ValueError("手柄按钮必须是整数编号（从 1 开始）") from exc
        if not button_value.is_integer():
            raise ValueError("手柄按钮必须是整数编号（从 1 开始）")
        button = int(button_value)
        if button < 1 or button > 32:
            raise ValueError("手柄按钮编号必须在 1 到 32 之间")
        timeout = max(0.0, min(86400.0, float(超时)))
        pause = max(0.01, min(2.0, float(间隔)))
        device_index = self._index(设备)
        deadline = time.monotonic() + timeout
        mask = 1 << (button - 1)
        desired = _as_bool(按下)
        while True:
            if self._winmm() is None:
                return ScriptResult({"ok": False, "kind": "joystick_button", "id": device_index, "button": button, "pressed": False, "connected": False})
            state = self.状态(device_index)
            pressed = bool(int(getattr(state, "buttons", 0) or 0) & mask) if state else False
            if pressed == desired:
                return ScriptResult({"ok": True, "kind": "joystick_button", "id": device_index, "button": button, "pressed": pressed, "connected": bool(getattr(state, "connected", False))})
            if self._host is not None and self._host.should_stop():
                raise ScriptError("手柄按钮等待已停止")
            if time.monotonic() >= deadline:
                return ScriptResult({"ok": False, "kind": "joystick_button", "id": device_index, "button": button, "pressed": pressed, "connected": bool(getattr(state, "connected", False))})
            time.sleep(pause)


class _WindowView:
    def __init__(self, host) -> None:
        self._host = host

    def 设置分辨率(self, *args, 报错=True):
        return self._host.设置分辨率(*args, 报错=报错)

    @staticmethod
    def _win32():
        try:
            import win32con
            import win32gui
            import win32process
        except Exception as exc:
            raise ScriptError(f"窗口 API 不可用: {exc}") from exc
        return win32con, win32gui, win32process

    def _resolve_hwnd(self, target: Any = None) -> int:
        """Resolve a script window argument without allowing arbitrary handles by accident."""
        _, win32gui, _ = self._win32()
        if target is None or str(target).strip() in {"", "当前", "绑定"}:
            target = self._host.context.get("target_hwnd")
        if isinstance(target, ScriptResult):
            target = target._payload.get("hwnd")
        elif isinstance(target, dict):
            target = target.get("hwnd")
        if isinstance(target, str) and not target.strip().isdigit():
            matches = []
            title = target.strip()
            def callback(hwnd, items):
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == title:
                    items.append(hwnd)
                return True

            win32gui.EnumWindows(callback, matches)
            if len(matches) != 1:
                if not matches:
                    raise ValueError(f"未找到窗口: {title}")
                raise ValueError(f"窗口标题不唯一: {title}")
            target = matches[0]
        try:
            hwnd = int(target)
        except (TypeError, ValueError) as exc:
            raise ValueError("窗口目标必须是 HWND、窗口标题或窗口信息") from exc
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise ValueError(f"窗口句柄无效: {hwnd}")
        return hwnd

    @staticmethod
    def _target_process_elevation(pid: Any) -> Optional[bool]:
        """Read a target process token elevation without requiring admin rights.

        ``None`` means the platform/API could not provide a reliable answer; it
        is deliberately kept distinct from ``False`` (known unelevated).
        """
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if not process:
                return None
            token = wintypes.HANDLE()
            try:
                if not ctypes.windll.advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
                    return None
                class _TokenElevation(ctypes.Structure):
                    _fields_ = [("TokenIsElevated", wintypes.DWORD)]

                elevation = _TokenElevation()
                size = wintypes.DWORD()
                if not ctypes.windll.advapi32.GetTokenInformation(
                    token, 20, ctypes.byref(elevation), ctypes.sizeof(elevation), ctypes.byref(size)
                ):
                    return None
                return bool(elevation.TokenIsElevated)
            finally:
                if token.value:
                    ctypes.windll.kernel32.CloseHandle(token)
                ctypes.windll.kernel32.CloseHandle(process)
        except Exception:
            return None

    def 信息(self, 目标: Any = None) -> dict:
        """Return stable metadata for a top-level or child window."""
        _, win32gui, win32process = self._win32()
        hwnd = self._resolve_hwnd(目标)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        info = {
            "hwnd": int(hwnd),
            "title": str(win32gui.GetWindowText(hwnd) or ""),
            "class_name": str(win32gui.GetClassName(hwnd) or ""),
            "pid": int(pid or 0),
            "visible": bool(win32gui.IsWindowVisible(hwnd)),
            "minimized": bool(win32gui.IsIconic(hwnd)),
            "x": int(left),
            "y": int(top),
            "width": max(0, int(right - left)),
            "height": max(0, int(bottom - top)),
            "client_width": max(0, int(client_right - client_left)),
            "client_height": max(0, int(client_bottom - client_top)),
        }
        info.update(
            {
                "句柄": info["hwnd"],
                "标题": info["title"],
                "类名": info["class_name"],
                "进程号": info["pid"],
                "可见": info["visible"],
                "最小化": info["minimized"],
                "宽": info["width"],
                "高": info["height"],
            }
        )
        return info

    def 枚举(self, 标题: Any = None, 类名: Any = None, 可见: Any = True) -> list:
        _, win32gui, win32process = self._win32()
        title_filter = str(标题 or "").strip()
        class_filter = str(类名 or "").strip()
        visible_only = _as_bool(可见)
        result = []

        def callback(hwnd, _):
            try:
                if visible_only and not win32gui.IsWindowVisible(hwnd):
                    return True
                title = str(win32gui.GetWindowText(hwnd) or "")
                class_name = str(win32gui.GetClassName(hwnd) or "")
                if title_filter and title_filter not in title:
                    return True
                if class_filter and class_filter not in class_name:
                    return True
                if not title and not class_name:
                    return True
                result.append(self.信息(hwnd))
            except Exception:
                return True
            return True

        win32gui.EnumWindows(callback, None)
        return result

    def 查找(self, 标题: Any, 完全匹配: Any = False, 可见: Any = True) -> list:
        text = str(标题 or "").strip()
        if not text:
            raise ValueError("窗口标题不能为空")
        rows = self.枚举(可见=可见)
        if _as_bool(完全匹配):
            return [row for row in rows if row.get("title") == text]
        return [row for row in rows if text in str(row.get("title") or "")]

    def 子窗口(self, 目标: Any = None, 搜索深度: Any = 10, 可见: Any = False) -> list:
        """Return descendants in parent-first order with an explicit depth."""
        _, win32gui, _ = self._win32()
        parent = self._resolve_hwnd(目标)
        max_depth = max(1, int(搜索深度))
        visible_only = _as_bool(可见)
        rows = []

        def walk(hwnd: int, depth: int) -> None:
            if depth > max_depth:
                return
            child = win32gui.GetWindow(hwnd, 5)  # GW_CHILD
            while child:
                try:
                    if not visible_only or win32gui.IsWindowVisible(child):
                        row = self.信息(child)
                        row["parent_hwnd"] = int(hwnd)
                        row["depth"] = depth
                        rows.append(row)
                    walk(child, depth + 1)
                    child = win32gui.GetWindow(child, 2)  # GW_HWNDNEXT
                except Exception:
                    break

        walk(parent, 1)
        return rows

    def Z序(self, 可见: Any = True) -> list:
        """Enumerate top-level windows in the OS Z-order."""
        _, win32gui, _ = self._win32()
        visible_only = _as_bool(可见)
        rows = []

        def callback(hwnd, _):
            try:
                if visible_only and not win32gui.IsWindowVisible(hwnd):
                    return True
                title = str(win32gui.GetWindowText(hwnd) or "")
                class_name = str(win32gui.GetClassName(hwnd) or "")
                if title or class_name:
                    row = self.信息(hwnd)
                    row["z_index"] = len(rows)
                    rows.append(row)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        return rows

    def DPI(self, 目标: Any = None) -> ScriptResult:
        _, win32gui, _ = self._win32()
        hwnd = self._resolve_hwnd(目标)
        getter = getattr(win32gui, "GetDpiForWindow", None)
        if not callable(getter):
            try:
                import ctypes
                getter = getattr(ctypes.windll.user32, "GetDpiForWindow", None)
            except Exception:
                getter = None
        dpi = int(getter(hwnd)) if callable(getter) else 96
        return ScriptResult({"ok": dpi > 0, "kind": "window", "hwnd": hwnd, "dpi": dpi, "scale": dpi / 96.0})

    def 坐标转换(self, x: Any, y: Any, 方向: Any = "屏幕到客户区", 目标: Any = None) -> ScriptResult:
        """在屏幕坐标与目标窗口客户区坐标之间转换，保留负坐标以支持多显示器。"""
        _, win32gui, _ = self._win32()
        hwnd = self._resolve_hwnd(目标)
        try:
            px, py = int(x), int(y)
        except (TypeError, ValueError) as exc:
            raise ValueError("坐标必须是整数") from exc
        direction = str(方向 or "屏幕到客户区").strip().casefold()
        screen_to_client = direction in {"屏幕到客户区", "屏幕转客户区", "screen_to_client", "screen2client"}
        client_to_screen = direction in {"客户区到屏幕", "客户区转屏幕", "client_to_screen", "client2screen"}
        if not (screen_to_client or client_to_screen):
            raise ValueError("坐标转换方向只能是 屏幕到客户区 或 客户区到屏幕")
        try:
            result = win32gui.ScreenToClient(hwnd, (px, py)) if screen_to_client else win32gui.ClientToScreen(hwnd, (px, py))
        except Exception as exc:
            raise ValueError(f"坐标转换失败: {exc}") from exc
        return ScriptResult({"ok": True, "kind": "coordinate", "x": int(result[0]), "y": int(result[1]), "hwnd": hwnd, "direction": "screen_to_client" if screen_to_client else "client_to_screen"})

    def 兼容性(self, 目标: Any = None) -> ScriptResult:
        """诊断当前脚本运行环境，供执行前判断 DPI/截图/UAC 能力。"""
        payload = {"ok": True, "kind": "compatibility", "platform": os.name}
        try:
            from utils.dpi_awareness import get_process_dpi_awareness
            awareness = get_process_dpi_awareness()
            payload["dpi_awareness"] = int(awareness)
            payload["dpi_aware"] = int(awareness) >= 1
        except Exception as exc:
            payload.update({"dpi_awareness": None, "dpi_aware": False, "dpi_error": str(exc)})
        try:
            # 直接读取统一截图引擎能力表，包含原生、DirectX/D3D 与 OpenGL 插件项。
            from utils.capture.screenshot_helper import get_screenshot_diagnostics
            screenshot_diag = dict(get_screenshot_diagnostics() or {})
            payload["screenshot"] = dict(screenshot_diag.get("capabilities") or {})
            payload["screenshot_diagnostics"] = screenshot_diag
            caps = payload["screenshot"]
            payload["directx"] = bool(
                caps.get("dxgi")
                or caps.get("dx")
                or caps.get("dx2")
                or caps.get("dx3")
                or caps.get("dx.graphic.2d")
                or caps.get("dx.graphic.2d.2")
                or caps.get("dx.graphic.3d")
                or caps.get("dx.graphic.3d.8")
                or caps.get("dx.graphic.3d.10plus")
            )
            payload["opengl"] = bool(
                caps.get("dx.graphic.opengl") or caps.get("dx.graphic.opengl.esv2")
            )
        except Exception as exc:
            payload.update({"screenshot": {}, "screenshot_diagnostics": {}, "directx": False, "opengl": False, "screenshot_error": str(exc)})
        try:
            import ctypes
            payload["admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else False
        except Exception:
            payload["admin"] = False
        try:
            user_threads = getattr(self._host, "_user_threads", {}) or {}
            watch_threads = getattr(self._host, "_watch_threads", {}) or {}
            active_user = sum(1 for thread in user_threads.values() if thread is not None and thread.is_alive())
            active_watch = sum(1 for thread in watch_threads.values() if thread is not None and thread.is_alive())
            from services.screenshot_pool import get_screenshot_worker_limit

            payload["runtime"] = {
                "python": platform.python_version(),
                "user_threads": active_user,
                "user_thread_limit": 32,
                "watch_threads": active_watch,
                "screenshot_worker_limit": int(get_screenshot_worker_limit()),
            }
        except Exception as exc:
            payload["runtime"] = {"python": platform.python_version(), "error": str(exc)}
        if 目标 is not None or self._host.context.get("target_hwnd"):
            try:
                hwnd = self._resolve_hwnd(目标)
                payload["hwnd"] = hwnd
                payload["window_dpi"] = self.DPI(hwnd).dpi
                try:
                    _, _, win32process = self._win32()
                    _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
                    payload["window_pid"] = int(pid)
                    elevated = self._target_process_elevation(pid)
                    payload["window_admin"] = elevated
                    payload["window_integrity"] = (
                        "高" if elevated is True else "中/低" if elevated is False else "未知"
                    )
                except Exception as exc:
                    payload.update({"window_admin": None, "window_integrity": "未知", "window_admin_error": str(exc)})
            except Exception as exc:
                payload["window_error"] = str(exc)
        return ScriptResult(payload)

    def 消息(self, 目标: Any, 消息: Any, wParam: Any = 0, lParam: Any = 0, 投递: Any = True) -> ScriptResult:
        win32con, win32gui, _ = self._win32()
        hwnd = self._resolve_hwnd(目标)
        names = {
            "关闭": win32con.WM_CLOSE, "激活": win32con.WM_ACTIVATE,
            "显示": win32con.WM_SHOWWINDOW, "隐藏": win32con.WM_SHOWWINDOW,
            "左键按下": win32con.WM_LBUTTONDOWN, "左键松开": win32con.WM_LBUTTONUP,
            "右键按下": win32con.WM_RBUTTONDOWN, "右键松开": win32con.WM_RBUTTONUP,
            "中键按下": win32con.WM_MBUTTONDOWN, "中键松开": win32con.WM_MBUTTONUP,
            "回车": win32con.WM_KEYDOWN, "复制": win32con.WM_COPY, "粘贴": win32con.WM_PASTE,
        }
        message_name = str(消息).strip() if isinstance(消息, str) else ""
        if message_name in names:
            code = names[message_name]
            # WM_SHOWWINDOW 的 wParam 明确表示显示(1)/隐藏(0)。
            if message_name == "显示" and wParam == 0:
                wParam = 1
            elif message_name == "隐藏" and wParam == 0:
                wParam = 0
        else:
            try:
                code = int(消息)
            except (TypeError, ValueError) as exc:
                raise ValueError("窗口消息必须是受支持的名称或整数消息号") from exc
        if code < 0 or code > 0xFFFF:
            raise ValueError("窗口消息号必须在 0 到 65535 之间")
        try:
            wParam = int(wParam or 0)
            lParam = int(lParam or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("窗口消息参数必须是整数") from exc
        if not -(2**31) <= wParam <= 0xFFFFFFFF or not -(2**31) <= lParam <= 0xFFFFFFFF:
            raise ValueError("窗口消息参数超出 32 位范围")
        sender = win32gui.PostMessage if _as_bool(投递) else win32gui.SendMessage
        result = sender(hwnd, code, wParam, lParam)
        return ScriptResult({"ok": True, "kind": "window_message", "hwnd": hwnd, "message": code, "result": result, "posted": _as_bool(投递)})

    def 激活(self, 目标: Any = None) -> bool:
        from utils.window.window_activation_utils import activate_window

        return bool(activate_window(self._resolve_hwnd(目标), log_prefix="自定义脚本"))

    def _element_simulator(self, 目标: Any = None):
        hwnd = self._resolve_hwnd(目标)
        try:
            from utils.input_simulation import InputSimulatorFactory, SimulatorBackend
            simulator = InputSimulatorFactory.create_simulator(
                hwnd=hwnd,
                operation_mode="auto",
                execution_mode=self._host.context.get("execution_mode", "foreground"),
                backend=SimulatorBackend.NATIVE,
            )
            if simulator is None:
                raise ScriptError("窗口元素 API 不可用: 无法创建 UIAutomation 模拟器")
            return simulator
        except Exception as exc:
            raise ScriptError(f"窗口元素 API 不可用: {exc}") from exc

    @staticmethod
    def _element_kwargs(名称=None, 自动化ID=None, 类名=None, 控件类型=None, 搜索深度=30, 超时=5.0):
        control_type_map = {
            "按钮": "ButtonControl", "编辑框": "EditControl", "文本": "TextControl",
            "复选框": "CheckBoxControl", "单选按钮": "RadioButtonControl", "下拉框": "ComboBoxControl",
            "列表": "ListControl", "列表项": "ListItemControl", "菜单": "MenuControl",
            "菜单项": "MenuItemControl", "树": "TreeControl", "树节点": "TreeItemControl",
            "选项卡": "TabControl", "选项卡项": "TabItemControl", "超链接": "HyperlinkControl",
            "窗口": "WindowControl", "面板": "PaneControl", "分组": "GroupControl",
            "数据表格": "DataGridControl", "表格": "TableControl", "无": None,
        }
        value = str(控件类型 or "").strip() or None
        return {
            "name": str(名称 or "").strip() or None,
            "automation_id": str(自动化ID or "").strip() or None,
            "class_name": str(类名 or "").strip() or None,
            "control_type": control_type_map.get(value, value),
            "search_depth": max(1, int(搜索深度)),
            "timeout": max(0.0, float(超时)),
        }

    def 查找元素(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        simulator = self._element_simulator(目标)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        elements = simulator.find_all_elements(**kwargs)
        start = max(0, int(序号))
        rows = []
        for element in elements[start:]:
            row = {}
            for key, attr in (("name", "Name"), ("automation_id", "AutomationId"), ("class_name", "ClassName"), ("control_type", "ControlTypeName")):
                try:
                    row[key] = getattr(element, attr, "") or ""
                except Exception:
                    row[key] = ""
            try:
                rect = element.BoundingRectangle
                row.update({"x": rect.left, "y": rect.top, "width": rect.width(), "height": rect.height()})
            except Exception:
                pass
            rows.append(row)
        return ScriptResult({"ok": bool(rows), "kind": "elements", "items": rows})

    def 元素文本(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        simulator = self._element_simulator(目标)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        elements = simulator.find_all_elements(**kwargs)
        index = max(0, int(序号))
        element = elements[index] if index < len(elements) else None
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        text = None
        pattern_errors = []
        try:
            value_pattern = element.GetValuePattern()
            if value_pattern:
                text = value_pattern.Value
        except Exception as exc:
            pattern_errors.append(str(exc))
        if text is None:
            try:
                text_pattern = element.GetTextPattern()
                if text_pattern:
                    text = text_pattern.DocumentRange.GetText(-1)
            except Exception as exc:
                pattern_errors.append(str(exc))
        if text is None:
            return ScriptResult({
                "ok": False,
                "kind": "element",
                "text": "",
                "error": "元素不支持读取文本" if not pattern_errors else "；".join(pattern_errors),
            })
        return ScriptResult({"ok": True, "kind": "element", "text": text or ""})

    def 设置元素值(self, 值, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        simulator = self._element_simulator(目标)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        elements = simulator.find_all_elements(**kwargs)
        index = max(0, int(序号))
        element = elements[index] if index < len(elements) else None
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            pattern = element.GetValuePattern()
            if not pattern:
                raise RuntimeError("元素不支持设置值")
            pattern.SetValue(str(值))
            return ScriptResult({"ok": True, "kind": "element", "value": str(值)})
        except Exception as exc:
            # UI Automation pattern 不可用时必须显式失败；不转换为点击、
            # 坐标输入或其他隐式动作，避免误操作目标窗口。
            return ScriptResult({"ok": False, "kind": "element", "value": str(值), "error": str(exc)})

    def _find_element_object(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None,
                             序号=0, 搜索深度=30, 超时=5.0, 目标=None):
        simulator = self._element_simulator(目标)
        kwargs = self._element_kwargs(名称, 自动化ID, 类名, 控件类型, 搜索深度, 超时)
        elements = simulator.find_all_elements(**kwargs)
        index = int(序号)
        if index < 0:
            raise ValueError("序号不能小于 0")
        return (elements[index] if index < len(elements) else None), simulator

    @staticmethod
    def _element_info(element: Any) -> dict:
        """读取常用 UIA 属性；单个属性读取失败不会影响其他属性。"""
        values = {}
        attrs = {
            "name": "Name", "automation_id": "AutomationId", "class_name": "ClassName",
            "control_type": "ControlTypeName", "enabled": "IsEnabled", "offscreen": "IsOffscreen",
            "focused": "HasKeyboardFocus",
        }
        for key, attr in attrs.items():
            try:
                values[key] = getattr(element, attr)
            except Exception:
                values[key] = "" if key in {"name", "automation_id", "class_name", "control_type"} else False
        try:
            rect = element.BoundingRectangle
            values.update({"x": int(rect.left), "y": int(rect.top), "width": int(rect.width()), "height": int(rect.height())})
        except Exception:
            pass
        values.update({"名称": values.get("name", ""), "自动化ID": values.get("automation_id", ""),
                       "类名": values.get("class_name", ""), "控件类型": values.get("control_type", "")})
        return values

    def 元素属性(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None):
        element, _ = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        return ScriptResult({"ok": True, "kind": "element", **self._element_info(element)})

    def 元素聚焦(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None):
        element, _ = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            element.SetFocus()
            return ScriptResult({"ok": True, "kind": "element", "action": "focus"})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "action": "focus", "error": str(exc)})

    def 元素切换(self, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None, 状态=None):
        element, _ = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            pattern = element.GetTogglePattern()
            if not pattern:
                raise RuntimeError("元素不支持勾选状态")
            desired = None if 状态 is None else _as_bool(状态)
            current = int(getattr(pattern, "ToggleState", 0))
            if desired is None or (desired and current == 0) or ((not desired) and current != 0):
                pattern.Toggle()
            state = int(getattr(pattern, "ToggleState", current))
            return ScriptResult({"ok": True, "kind": "element", "checked": state != 0, "state": state})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "error": str(exc)})

    def 元素选择(self, 值=None, 名称=None, 自动化ID=None, 类名=None, 控件类型=None, 序号=0,
                 搜索深度=30, 超时=5.0, 目标=None):
        element, simulator = self._find_element_object(名称, 自动化ID, 类名, 控件类型, 序号, 搜索深度, 超时, 目标)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            target = element
            if 值 is not None:
                # ComboBox/List 选择项：优先在控件子树按名称精确找 ListItem。
                candidates = simulator.find_all_elements(name=str(值), control_type="ListItemControl", search_depth=搜索深度, timeout=超时)
                if candidates:
                    target = candidates[0]
            pattern = target.GetSelectionItemPattern()
            if not pattern:
                raise RuntimeError("元素不支持选择")
            pattern.Select()
            return ScriptResult({"ok": True, "kind": "element", "value": "" if 值 is None else str(值)})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "error": str(exc)})

    def _元素展开折叠(self, expand: bool, **kwargs):
        element, _ = self._find_element_object(**kwargs)
        if element is None:
            return ScriptResult({"ok": False, "kind": "element"})
        try:
            pattern = element.GetExpandCollapsePattern()
            if not pattern:
                raise RuntimeError("元素不支持展开折叠")
            (pattern.Expand if expand else pattern.Collapse)()
            return ScriptResult({"ok": True, "kind": "element", "expanded": bool(expand)})
        except Exception as exc:
            return ScriptResult({"ok": False, "kind": "element", "error": str(exc)})

    def 元素展开(self, **kwargs):
        return self._元素展开折叠(True, **kwargs)

    def 元素折叠(self, **kwargs):
        return self._元素展开折叠(False, **kwargs)

    def 关闭(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        return bool(win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0))

    def 显示(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        return True

    def 隐藏(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        return True

    def 最小化(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return True

    def 还原(self, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        return True

    def 移动(self, x: Any, y: Any, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
        return True

    def 大小(self, 宽: Any, 高: Any, 目标: Any = None) -> bool:
        _, win32gui, win32process = self._win32()
        _ = win32process
        hwnd = self._resolve_hwnd(目标)
        import win32con

        win32gui.SetWindowPos(hwnd, 0, 0, 0, int(宽), int(高), win32con.SWP_NOMOVE | win32con.SWP_NOZORDER)
        return True

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise ScriptError("禁止访问该属性")
        width, height = self._host.客户区尺寸()
        if name in {"宽", "宽度"}:
            return width
        if name in {"高", "高度"}:
            return height
        raise ScriptError(f"没有字段: {name}")


class _ClipboardApi:
    def 获取(self) -> str:
        return clipboard_get()

    def 设置(self, text: Any) -> str:
        return clipboard_set(text)


class _ProcessView:
    """Process helpers; starting/stopping processes requires trusted components."""

    def __init__(self, host) -> None:
        self._host = host

    @staticmethod
    def _psutil():
        try:
            import psutil
        except Exception as exc:
            raise ScriptError(f"进程 API 不可用: {exc}") from exc
        return psutil

    def 查找(self, 名称: Any = None) -> list:
        psutil = self._psutil()
        needle = str(名称 or "").strip().casefold()
        rows = []
        for proc in psutil.process_iter(["pid", "name", "exe", "status"]):
            try:
                info = proc.info
                name = str(info.get("name") or "")
                exe = str(info.get("exe") or "")
                if needle and needle not in name.casefold() and needle not in exe.casefold():
                    continue
                rows.append(
                    ScriptResult(
                        {
                            "pid": int(info.get("pid") or 0),
                            "name": name,
                            "path": exe,
                            "status": str(info.get("status") or ""),
                        },
                        ok=True,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return rows

    def 信息(self, 进程号: Any) -> dict:
        psutil = self._psutil()
        try:
            proc = psutil.Process(int(进程号))
            with proc.oneshot():
                return ScriptResult(
                    {
                        "pid": int(proc.pid),
                        "name": str(proc.name() or ""),
                        "path": str(proc.exe() or ""),
                        "status": str(proc.status() or ""),
                        "create_time": float(proc.create_time() or 0),
                    },
                    ok=True,
                )
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            raise ValueError(f"无法读取进程: {进程号}") from exc

    def 是否运行(self, 目标: Any) -> bool:
        psutil = self._psutil()
        if isinstance(目标, (int, float)) and not isinstance(目标, bool):
            try:
                return bool(psutil.pid_exists(int(目标)))
            except Exception:
                return False
        return bool(self.查找(目标))

    def _require_trust(self) -> None:
        if not bool(self._host.context.get("allow_external_components", False)):
            raise ScriptError("进程启动/关闭需要启用并信任外部组件")

    def 启动(self, 程序: Any, 参数: Any = None, 等待: Any = False, 超时: Any = 30) -> dict:
        self._require_trust()
        import subprocess

        executable = str(程序 or "").strip()
        if not executable:
            raise ValueError("程序不能为空")
        from task_workflow.script_resources import _is_module_offset_literal

        if _is_module_offset_literal(executable):
            raise ValueError("这是模块地址，不能当程序启动")
        if 参数 is None:
            args = []
        elif isinstance(参数, (list, tuple)):
            args = [str(item) for item in 参数]
        else:
            args = [str(参数)]
        wait_for_exit = _as_bool(等待)
        proc = subprocess.Popen(
            [executable, *args],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if wait_for_exit else subprocess.DEVNULL,
            stderr=subprocess.PIPE if wait_for_exit else subprocess.DEVNULL,
            text=True,
        )
        result = {
            "pid": int(proc.pid),
            "running": proc.poll() is None,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        if wait_for_exit:
            try:
                stdout, stderr = proc.communicate(timeout=max(0.0, float(超时)))
            except subprocess.TimeoutExpired:
                result["running"] = True
                result["stdout"] = ""
                result["stderr"] = ""
            else:
                result.update(
                    {
                        "running": False,
                        "exit_code": proc.returncode,
                        "stdout": stdout or "",
                        "stderr": stderr or "",
                    }
                )
        return ScriptResult(result, ok=True)

    def 关闭(self, 进程号: Any, 强制: Any = False) -> bool:
        self._require_trust()
        psutil = self._psutil()
        try:
            proc = psutil.Process(int(进程号))
            proc.kill() if _as_bool(强制) else proc.terminate()
            return True
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            raise ValueError(f"无法关闭进程: {进程号}") from exc


class _NetworkView:
    """Bounded HTTP client for explicitly trusted scripts."""

    def __init__(self, host) -> None:
        self._host = host

    def 请求(self, 地址: Any, 方法: Any = "GET", 数据: Any = None, 头: Any = None, 超时: Any = 15, 最大字节: Any = 2 * 1024 * 1024) -> ScriptResult:
        if not bool(self._host.context.get("allow_external_components", False)):
            raise ScriptError("网络请求需要启用并信任外部组件")
        from urllib.parse import urlparse
        from urllib.request import Request, urlopen

        url = str(地址 or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("网络地址只允许 http 或 https")
        method = str(方法 or "GET").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
            raise ValueError("网络方法不受支持")
        headers = {}
        if 头 is not None:
            if not isinstance(头, dict):
                raise TypeError("网络请求头必须是字典")
            headers = {str(key): str(value) for key, value in 头.items()}
        body = None
        if 数据 is not None:
            if isinstance(数据, (dict, list, tuple)):
                body = json.dumps(数据, ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json; charset=utf-8")
            else:
                body = str(数据).encode("utf-8")
        limit = max(1, min(10 * 1024 * 1024, int(最大字节)))
        try:
            request = Request(url, data=body, headers=headers, method=method)
            with urlopen(request, timeout=max(0.1, min(120.0, float(超时)))) as response:
                chunks = []
                total = 0
                while True:
                    chunk = response.read(min(64 * 1024, limit - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= limit:
                        break
                raw = b"".join(chunks)
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
                return ScriptResult({"ok": 200 <= int(response.status) < 400, "kind": "http", "status": int(response.status), "headers": dict(response.headers.items()), "text": text, "bytes": len(raw), "url": url})
        except Exception as exc:
            raise ValueError(f"网络请求失败: {exc}") from exc


class _EventView:
    def __init__(self, host) -> None:
        self._host = host

    def _wait(self, check, 超时: Any, 间隔: Any, kind: str) -> ScriptResult:
        timeout = max(0.0, min(86400.0, float(超时)))
        pause = max(0.05, min(10.0, float(间隔)))
        deadline = time.monotonic() + timeout
        while True:
            if self._host.should_stop():
                raise ScriptError("事件等待已停止")
            value = check()
            if value:
                if isinstance(value, ScriptResult):
                    return value
                return ScriptResult({"ok": True, "kind": kind, "value": value})
            if time.monotonic() >= deadline:
                return ScriptResult({"ok": False, "kind": kind})
            time.sleep(pause)

    def 等待窗口(self, 标题: Any, 完全匹配: Any = False, 超时: Any = 30, 间隔: Any = 0.3) -> ScriptResult:
        view = _WindowView(self._host)
        text = str(标题 or "").strip()
        if not text:
            raise ValueError("事件窗口标题不能为空")
        return self._wait(lambda: (view.查找(text, 完全匹配=完全匹配) or [None])[0], 超时, 间隔, "window_event")

    def 等待进程(self, 目标: Any, 超时: Any = 30, 间隔: Any = 0.5) -> ScriptResult:
        view = _ProcessView(self._host)
        def check():
            if isinstance(目标, (int, float)) and not isinstance(目标, bool):
                return ScriptResult({"ok": view.是否运行(目标), "kind": "process_event", "pid": int(目标)}) if view.是否运行(目标) else None
            rows = view.查找(目标)
            return rows[0] if rows else None
        return self._wait(check, 超时, 间隔, "process_event")

    def 等待窗口关闭(self, 目标: Any, 超时: Any = 30, 间隔: Any = 0.3) -> ScriptResult:
        view = _WindowView(self._host)
        target = 目标
        def check():
            try:
                hwnd = view._resolve_hwnd(target)
                return None if hwnd else True
            except Exception:
                return True
        return self._wait(check, 超时, 间隔, "window_closed_event")

    def 等待进程退出(self, 目标: Any, 超时: Any = 30, 间隔: Any = 0.5) -> ScriptResult:
        view = _ProcessView(self._host)
        def check():
            if isinstance(目标, (int, float)) and not isinstance(目标, bool):
                return not view.是否运行(目标)
            return not bool(view.查找(目标))
        return self._wait(check, 超时, 间隔, "process_exit_event")

    def 等待文件(self, 文件: Any, 存在: Any = True, 超时: Any = 30, 间隔: Any = 0.5) -> ScriptResult:
        path = str(文件 or "").strip()
        if not path:
            raise ValueError("事件文件路径不能为空")
        if not os.path.isabs(path):
            raise ValueError("事件文件路径必须是绝对路径")
        want_exists = _as_bool(存在)
        def check():
            return os.path.isfile(path) == want_exists
        return self._wait(check, 超时, 间隔, "file_event")


class _HotkeyView:
    def __init__(self, host, callback_resolver) -> None:
        self._host = host
        self._callback_resolver = callback_resolver

    def 注册(self, 按键: Any, 回调: Any, 名字: Any = None) -> ScriptResult:
        callback = self._callback_resolver(回调)
        label = str(名字 or 按键 or "热键").strip() or "热键"
        return self._host.注册热键(按键, callback, label)

    def 注销(self, 名字: Any) -> bool:
        return self._host.注销热键(名字)

    def 全部注销(self) -> int:
        return self._host.全部注销热键()


class _TimerView:
    def __init__(self, host, callback_resolver) -> None:
        self._host = host
        self._callback_resolver = callback_resolver

    def 启动(self, 名字: Any, 间隔: Any, 回调: Any, 次数: Any = 0) -> ScriptResult:
        callback = self._callback_resolver(回调)
        return self._host.启动定时器(名字, 间隔, callback, 次数=次数)

    def 停止(self, 名字: Any) -> ScriptResult:
        return self._host.停止定时器(名字)


class _ExternalComponentApi:
    def __init__(self, host: CommandHost) -> None:
        self._host = host

    def 加载(self, 类型: Any, 入口: Any, 调用约定: Any = "cdecl", 超时: Any = 10) -> ScriptResult:
        return self._host.组件加载(类型, 入口, 调用约定=调用约定, 超时=超时)

    def 调用(self, 句柄: Any, 方法: Any = "", *参数: Any, **选项: Any) -> ScriptResult:
        return self._host.组件调用(句柄, 方法, *参数, **选项)

    def 读取(self, 句柄: Any, 属性: Any, 超时: Any = 30) -> ScriptResult:
        return self._host.组件读取(句柄, 属性, 超时=超时)

    def 写入(self, 句柄: Any, 属性: Any, 值: Any, 超时: Any = 30) -> ScriptResult:
        return self._host.组件写入(句柄, 属性, 值, 超时=超时)

    def 运行(self, 程序: Any, *参数: Any, **选项: Any) -> ScriptResult:
        return self._host.组件运行(程序, *参数, **选项)

    def 关闭(self, 句柄: Any = None, 超时: Any = 5) -> ScriptResult:
        return self._host.组件关闭(句柄, 超时=超时)


def run_script(
    source: str,
    store: RuntimeStore,
    logger_obj: Optional[logging.Logger] = None,
    context: Optional[Dict[str, Any]] = None,
    modules: Optional[Dict[str, Any]] = None,
    invoke=None,
) -> tuple[bool, str]:
    validate_script(source)
    placeholder = unfilled_placeholder_error(source)
    if placeholder:
        raise ScriptError(placeholder)
    tree = parse_script(source)
    user_funcs = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    tree = _ForCountWrap().visit(tree)
    tree = _GuardInsert().visit(tree)
    ast.fix_missing_locations(tree)
    runtime_logger = logger_obj or logger
    runtime_context = dict(context or {})
    host = CommandHost(store, runtime_context, runtime_logger, modules=modules, invoke=invoke)

    def _script_stop() -> bool:
        return host.should_stop()

    runtime_context["stop_checker"] = _script_stop
    host.context["stop_checker"] = _script_stop
    guard = _Guard(
        stop_checker=_script_stop,
        pause_checker=runtime_context.get("pause_checker"),
    )

    def _log(message: Any) -> None:
        runtime_logger.info("[自定义脚本] %s", message)

    def _ok(detail: Any = "") -> None:
        raise ScriptOutcome(True, str(detail or ""))

    def _fail(detail: Any = "") -> None:
        raise ScriptOutcome(False, str(detail or "判断失败"))

    def _is_user_func(func: Any) -> bool:
        name = str(getattr(func, "__name__", "") or "")
        return name in user_funcs and namespace.get(name) is func

    def _resolve_user_callback(target: Any) -> Any:
        callback = target
        if isinstance(target, str):
            if target not in user_funcs:
                raise ScriptError(f"回调请传入子程序，例如 回调={target}")
            callback = namespace.get(target)
        if not callable(callback) or not _is_user_func(callback):
            raise ScriptError("回调请传入脚本中的子程序")
        return callback

    def _start_thread(目标: Any, 名字: Any = None) -> Any:
        func = 目标
        label = 名字
        if isinstance(目标, str):
            if 目标 not in user_funcs:
                raise ScriptError("多线程请传入子程序，例如 多线程(按W)")
            func = namespace.get(目标)
            if not callable(func):
                raise ScriptError(f"没有这个子程序：{目标}")
            label = 名字 or 目标
        if not callable(func) or not _is_user_func(func):
            raise ScriptError("多线程请传入子程序，例如 多线程(按W)")
        return host.多线程(func, label)

    namespace = _ScriptNamespace({
        "__builtins__": {},
        "__guard": guard,
        "__iter_count": script_for_iterable,
        "变量": _VarsApi(store),
        "区域": _RegionApi(host),
        "上次": _StoreView(store),
        "文字": _StoreView(store, "ocr"),
        "找图": _CallableLast(host.找图, store, "image", host),
        "等图": _CallableLast(host.等图, store, "image", host),
        "找所有图": _CallableLast(host.找所有图, store, "image", host),
        "检测": _CallableLast(host.检测, store, "yolo", host),
        "框内点": host.框内点,
        "随机点": host.随机点,
        "距离": host.距离,
        "角度": host.角度,
        "等检测": _CallableLast(host.等检测, store, "yolo", host),
        "等检测消失": host.等检测消失,
        "持续检测": host.持续检测,
        "停止检测": host.停止检测,
        "持续找图": host.持续找图,
        "停止找图": host.停止找图,
        "多线程": _start_thread,
        "关闭线程": host.关闭线程,
        "线程状态": host.线程状态,
        "等待线程": host.等待线程,
        "线程结果": host.线程结果,
        "卡片": _CardView(store),
        "窗口": _WindowView(host),
        "输入设备": _InputDeviceView(host),
        "进程": _ProcessView(host),
        "网络": _NetworkView(host),
        "事件": _EventView(host),
        "热键": _HotkeyView(host, _resolve_user_callback),
        "定时器": _TimerView(host, _resolve_user_callback),
        "剪贴板": _ClipboardApi(),
        "组件": _ExternalComponentApi(host),
        "数据": _DataApi(),
        "性能": _PerformanceView(host),
        "大漠内存": _DmMemoryView(host),
        "大漠汇编": _DmAsmView(host),
        "点击": host.点击,
        "按下": host.按下,
        "松开": host.松开,
        "按住": host.按住,
        "连点": host.连点,
        "找色": host.找色,
        "移动": host.移动,
        "相对移动": host.相对移动,
        "鼠标位置": host.鼠标位置,
        "拖拽": host.拖拽,
        "滚轮": host.滚轮,
        "按键": host.按键,
        "输入": host.输入,
        "延时": host.延时,
        "等毫秒": host.等毫秒,
        "播放": host.播放,
        "停止播放": host.停止播放,
        "回放": host.回放,
        "暂停回放": host.暂停回放,
        "继续回放": host.继续回放,
        "停止回放": host.停止回放,
        "截图": _CallableLast(host.截图, store, "image", host),
        "等按键": host.等按键,
        "找字": host.找字,
        "找字库": host.找字库,
        "等字库": host.等字库,
        "等字库消失": host.等字库消失,
        "点字库": host.点字库,
        "等色": host.等色,
        "等文字": host.等文字,
        "等图消失": host.等图消失,
        "等色消失": host.等色消失,
        "等文字消失": host.等文字消失,
        "取色": host.取色,
        "比色": host.比色,
        "点文字": host.点文字,
        "点元素": host.点元素,
        "记录": _log,
        "成功": _ok,
        "失败": _fail,
        # These Python names are internal targets of the Chinese aliases
        # above, not public script commands.
        "len": len,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "min": min,
        "max": max,
        "abs": abs,
        "range": range,
        "长度": len,
        "整数": int,
        "小数": float,
        "到文本": str,
        "真假": bool,
        "最小": min,
        "最大": max,
        "绝对值": abs,
        "开方": script_sqrt,
        "平方根": script_sqrt,
        "正弦": script_sin,
        "余弦": script_cos,
        "限制": script_clamp,
        "范围": range,
        "枚举": enumerate,
        "配对": zip,
        "排序": script_sort,
        "四舍五入": script_round,
        "全部": all,
        "任一": any,
        "随机": script_random,
        "包含": script_contains,
        "截取": script_slice,
        "替换": script_replace,
        "分割": script_split,
        "时间": script_now_ms,
        "JSON解析": script_json_parse,
        "JSON生成": script_json_dump,
        "字典获取": script_dict_get,
        "字典设置": script_dict_set,
        "列表追加": script_list_append,
        "列表弹出": script_list_pop,
        "类型": script_type,
        "断言": script_assert,
        "字典键": script_dict_keys,
        "字典值": script_dict_values,
        "列表合并": script_list_extend,
        "开头是": script_startswith,
        "结尾是": script_endswith,
        "去空格": script_strip,
        "查找": script_find,
        "提取数字": script_extract_number,
        "Exception": Exception,
        "BaseException": BaseException,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "RuntimeError": RuntimeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "ZeroDivisionError": ZeroDivisionError,
        "StopIteration": StopIteration,
        "NameError": NameError,
        "ArithmeticError": ArithmeticError,
        "AssertionError": AssertionError,
    })
    for name in COMMAND_NAMES:
        value = dict.get(namespace, name)
        if value is not None:
            namespace.install_command(name, value)
    result = None
    previous_trace = None
    debugger = runtime_context.get("debugger")
    if debugger is not None and callable(getattr(debugger, "start", None)):
        # 只有完全没有生命周期管理（没有可调用 is_running）的简易/旧式调试器，才由
        # run_script 代为启动。带 is_running() 的调试器 start/stop 归调用方所有：
        # 若这里代它 start()，会把调用方在进入 run_script 前发出的 stop() 抹掉，
        # 令“停止后仍继续运行”。
        is_running = getattr(debugger, "is_running", None)
        if not callable(is_running):
            try:
                debugger.start()
            except Exception:
                logger.debug("启动脚本调试器失败", exc_info=True)
    try:
        try:
            # 调试器仅在本次脚本执行期间安装逐行追踪，结束后恢复宿主线程原有设置。
            trace = getattr(debugger, "trace", None) if debugger is not None else None
            if callable(trace):
                def _script_trace(frame, event, arg):
                    if frame.f_code.co_filename != "<script>":
                        return None
                    return trace(frame, event, arg)
                previous_trace = sys.gettrace()
                sys.settrace(_script_trace)
            exec(compile(tree, "<script>", "exec"), namespace, namespace)  # noqa: S102
            result = (True, "")
        except ScriptOutcome as outcome:
            result = (outcome.success, outcome.detail)
        except ScriptError:
            raise
        except AttributeError as exc:
            message = str(exc)
            name = getattr(exc, "name", "") or ""
            if "没有字段" in message:
                _raise_script_error(message, exc)
            _raise_script_error(f"没有字段: {name or message}", exc)
        except ZeroDivisionError as exc:
            _raise_script_error("除数不能为 0", exc)
        except TypeError as exc:
            message = str(exc)
            if "int" in message and ("literal" in message or "argument" in message):
                _raise_script_error("坐标必须是数字，文字请用 点文字()", exc)
            _raise_script_error(f"参数不对: {message}", exc)
        except ValueError as exc:
            message = str(exc)
            if message.startswith(("不允许", "未找到", "能力不可", "已停止", "点击缺少", "移动缺少", "拖拽缺少", "取色缺少", "框内点缺少", "随机点缺少", "距离缺少", "角度缺少", "开方", "多线程", "检测", "持续检测", "持续找图", "没有框", "停止检查", "暂停检查", "文字请用", "区域请写成", "没有这个区域", "宽和高", "策略只能", "区域名", "区域.设置", "单独一个", "宽高", "窗口", "没有当前", "没有可调整", "当前窗口", "脚本不能", "缺少资源", "回放", "不认识", "截图", "等按键", "外部组件", "变量名", "步长", "循环次数")):
                _raise_script_error(message, exc)
            _raise_script_error(f"运行失败: {message}", exc)
        except NameError as exc:
            name = getattr(exc, "name", None) or ""
            if name in _PLACEHOLDER_NAMES:
                _raise_script_error(unfilled_placeholder_error(source) or f"还没填写参数：{name}", exc)
            message = str(exc)
            for placeholder in _PLACEHOLDER_NAMES:
                if f"'{placeholder}'" in message:
                    _raise_script_error(unfilled_placeholder_error(source) or f"还没填写参数：{placeholder}", exc)
            if name:
                _raise_script_error(f"没有这个名字：{name}", exc)
            _raise_script_error(f"运行失败: {exc}", exc)
        except Exception as exc:
            message = str(exc)
            if "outside function" in message and "return" in message:
                _raise_script_error("不能单独写返回，请用 成功() 或 失败()", exc)
            _raise_script_error(f"运行失败: {exc}", exc)
    finally:
        if debugger is not None and callable(getattr(debugger, "finish", None)):
            try:
                pending = sys.exc_info()[1]
                if pending is not None:
                    # 有异常正在向外传播：以失败和异常文本收尾，避免用陈旧的 result
                    # 误报成功；同时保证异常路径上 finish 只在这里发生一次。
                    debugger.finish(False, str(pending))
                else:
                    success = result[0] if isinstance(result, tuple) and result else None
                    detail = result[1] if isinstance(result, tuple) and len(result) > 1 else ""
                    debugger.finish(success, detail)
            except Exception:
                logger.debug("结束脚本调试器失败", exc_info=True)
        if callable(getattr(debugger, "trace", None)):
            try:
                sys.settrace(previous_trace)
            except Exception:
                sys.settrace(None)
        host.close()
    failure = host.thread_failure()
    if failure:
        raise ScriptError(f"线程失败: {failure}")
    return result if result is not None else (True, "")
