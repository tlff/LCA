"""AI assistant chat helpers.

The UI talks to any OpenAI-compatible chat-completions endpoint. The module
keeps transport and the knowledge document out of the Qt dialog so it can also
be used by tests or a future non-Qt client.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import time
import hashlib
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
import inspect
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DEFAULT_BASE_URL = "https://lcaa.xyz/v1"
DEFAULT_MODEL = "gpt-5.5"
MAX_PROMPT_CHARS = 12000
MAX_WORKFLOW_CONTEXT_CHARS = 32000
MAX_PARAM_VALUE_CHARS = 6000
CAPABILITY_DOC_NAME = "WORKFLOW_AND_SCRIPTS.md"
KNOWLEDGE_DOC_NAME = "AI_ASSISTANT_KNOWLEDGE.md"
_SKIP_PARAM_TYPES = {"separator", "hidden", "button"}
_LINE_TYPE_LABELS = {
    "sequential": "顺序",
    "success": "成功",
    "failure": "失败",
    "random": "随机",
}
AI_REQUEST_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (0.4, 1.2)
_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
_RETRYABLE_TEXT = (
    "remote end closed",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "timed out",
    "temporarily unavailable",
    "eof occurred",
)
_CACHE_LOCK = threading.RLock()
_RESPONSE_CACHE: Dict[str, tuple[float, str]] = {}
AI_CACHE_TTL_SECONDS = 900
AI_CACHE_MAX_ENTRIES = 64
AI_CACHE_SCHEMA_VERSION = "2"
_CACHE_HITS = 0
_CACHE_MISSES = 0
_KNOWLEDGE_HEADER = (
    "本文列出 LCA 全部现行卡片参数和全部自定义脚本命令，以及工作流规则。"
    "查阅卡片、参数、端口和脚本命令时，只使用本文及后面的运行时目录；"
    "不要编造已删除的卡片名、参数名、命令或旧别名。"
)
_CHAT_SYSTEM_PROMPT = (
    "你是 LCA 的 AI 助手。下面是产品说明文档。"
    "若附有「当前正在编辑的工作流」，那是用户当前画布上的现行内容，包含未保存修改；"
    "回答当前流程、当前卡片或当前脚本的问题时必须以这份快照为准。"
    "用户要求审查或修正时，按说明文档检查结构、连线、卡片参数和自定义脚本，先用中文说明问题和改法。"
    "需要改画布时，必须输出一个语言标记为 工作流 的代码块，内容是只含 ops 数组的 JSON；"
    "未改动的卡片不要写进 ops。不要编造已删除的卡片名、参数名、命令或旧别名。"
    "禁止把卡片输出连到自己；循环必须经过另一张有输入口的卡片再连回来。"
    "用户点击「应用」后才会写入当前正在编辑的工作流；未点击前画布不变。"
)
REVIEW_WORKFLOW_PROMPT = (
    "请审查当前正在编辑的工作流。"
    "指出结构、连线、卡片参数和自定义脚本中的问题，并说明原因。"
    "若可以修正，先用中文说明改了什么，再给出一个完整的 ```工作流 JSON 代码块供我点应用。"
    "没有问题时明确说没有发现问题，不要输出工作流代码块。"
)
_WORKFLOW_CONTEXT_HEADER = "## 当前正在编辑的工作流"


def _cache_key(config: AIProviderConfig, messages: Iterable[Mapping[str, str]]) -> str:
    payload = {
        "schema": AI_CACHE_SCHEMA_VERSION,
        "endpoint": config.endpoint(),
        "model": str(config.model or DEFAULT_MODEL),
        "messages": [dict(item) for item in messages],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def clear_ai_response_cache() -> None:
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        _RESPONSE_CACHE.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0


def ai_response_cache_stats() -> Dict[str, int]:
    """Return cache size for diagnostics without exposing cached content."""
    now = time.time()
    with _CACHE_LOCK:
        expired = [key for key, (stamp, _) in _RESPONSE_CACHE.items()
                   if now - stamp >= AI_CACHE_TTL_SECONDS]
        for key in expired:
            _RESPONSE_CACHE.pop(key, None)
        return {"entries": len(_RESPONSE_CACHE), "max_entries": AI_CACHE_MAX_ENTRIES,
                "hits": _CACHE_HITS, "misses": _CACHE_MISSES}


def load_ai_provider_settings() -> Dict[str, Any]:
    """Load API connection settings from this instance's local store."""
    values = {
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "api_key": "",
        "timeout": 90,
    }
    try:
        from utils.instance_runtime import create_app_settings

        settings = create_app_settings()
        saved_base_url = str(settings.value("ai/base_url", "") or "").strip()
        values["base_url"] = normalize_ai_base_url(saved_base_url or DEFAULT_BASE_URL)
        saved_model = str(settings.value("ai/model", "") or "").strip()
        values["model"] = saved_model or DEFAULT_MODEL
        values["api_key"] = str(settings.value("ai/api_key", ""))
        values["timeout"] = int(settings.value("ai/timeout", values["timeout"]))
    except Exception:
        pass
    return values


def normalize_ai_base_url(base_url: str) -> str:
    """Append /v1 when missing. Keep an existing /v1. Empty falls back to default."""
    base = str(base_url or "").strip()
    if not base:
        return DEFAULT_BASE_URL
    base = base.rstrip("/")
    completions = "/chat/completions"
    if base.endswith(completions):
        base = base[: -len(completions)].rstrip("/")
    if not base.lower().endswith("/v1"):
        base = f"{base}/v1"
    return base


def save_ai_provider_settings(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
) -> None:
    from utils.instance_runtime import create_app_settings

    settings = create_app_settings()
    settings.setValue("ai/base_url", normalize_ai_base_url(base_url))
    settings.setValue("ai/model", str(model or "").strip())
    settings.setValue("ai/api_key", str(api_key or ""))
    settings.setValue("ai/timeout", int(timeout or 90))


@dataclass(frozen=True)
class AIProviderConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    timeout: int = 90

    def endpoint(self) -> str:
        return f"{normalize_ai_base_url(self.base_url)}/chat/completions"


def _format_ai_http_error(status_code: int, detail: str) -> str:
    text = str(detail or "").strip()
    if status_code == 403 and "1010" in text:
        return (
            "AI 服务返回 HTTP 403（Cloudflare 1010）：请求被网站的浏览器完整性检查拦截了，"
            "还没到达模型接口。请确认网关已放行桌面客户端，或在 Cloudflare 里对 /v1 关闭 Browser Integrity Check。"
        )
    if text:
        return f"AI 服务返回 HTTP {status_code}: {text}"
    return f"AI 服务返回 HTTP {status_code}"


def model_supports_temperature(model: str) -> bool:
    """Newer chat/reasoning models often reject a custom temperature."""
    name = str(model or "").strip().lower()
    return not name.startswith(("gpt-5", "o1", "o3", "o4"))


def build_chat_payload(
    config: AIProviderConfig,
    messages: Iterable[Mapping[str, str]],
    *,
    include_temperature: Optional[bool] = None,
) -> Dict[str, Any]:
    model = str(config.model or DEFAULT_MODEL).strip()
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
            for item in messages
        ],
    }
    if include_temperature if include_temperature is not None else model_supports_temperature(model):
        payload["temperature"] = 0.2
    return payload


def _ai_request_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {str(api_key).strip()}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": "LCA-Desktop/1.0",
    }


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return str(getattr(exc, "reason", "") or exc)
    return str(exc)


def is_retryable_ai_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return int(getattr(exc, "code", 0) or 0) in _RETRYABLE_HTTP_STATUS
    if isinstance(
        exc,
        (
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
            http.client.BadStatusLine,
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            TimeoutError,
            socket.timeout,
        ),
    ):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException) and is_retryable_ai_error(reason):
            return True
    text = _error_text(exc).lower()
    return any(token in text for token in _RETRYABLE_TEXT)


def _temperature_rejected(status_code: int, detail: str) -> bool:
    if int(status_code) not in {400, 422}:
        return False
    text = str(detail or "").lower()
    return "temperature" in text


def format_ai_transport_error(exc: BaseException) -> str:
    text = _error_text(exc)
    lowered = text.lower()
    if any(token in lowered for token in ("remote end closed", "connection reset", "broken pipe", "eof occurred")):
        return (
            "AI 服务在返回结果前断开了连接。多半是网关瞬时断开或请求较大，"
            "请再试一次；若反复出现，可把超时调大，或换一个可用的模型和地址。"
        )
    if any(token in lowered for token in ("timed out", "timeout")):
        return "等待 AI 服务超时。请把超时调大后再试，或检查网络和接口地址。"
    if text:
        return f"无法连接 AI 服务: {text}"
    return "无法连接 AI 服务"


def _read_http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:500]
    except Exception:
        return ""


def _post_chat_request(
    request: urllib.request.Request,
    timeout: int,
    opener: Callable[..., Any],
) -> str:
    with opener(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _parse_chat_completion(raw: str) -> str:
    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI 服务响应不是有效的 chat-completions 格式") from exc
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    text = str(content or "").strip()
    if not text:
        raise RuntimeError("AI 返回了空内容")
    return text


def chat_completion(
    config: AIProviderConfig,
    messages: Iterable[Mapping[str, str]],
    *,
    opener: Optional[Callable[..., Any]] = None,
    use_cache: bool = True,
) -> str:
    """Call an OpenAI-compatible endpoint and return its text content."""
    if not str(config.api_key or "").strip():
        raise ValueError("请先填写 API Key")
    message_list = list(messages)
    # 注入 opener 通常用于测试或切换传输通道；不能复用另一通道的缓存，
    # 否则网络失败会被旧响应掩盖，也会让重试行为不可测。
    key = _cache_key(config, message_list) if (use_cache and opener is None) else ""
    if key:
        global _CACHE_HITS, _CACHE_MISSES
        with _CACHE_LOCK:
            cached = _RESPONSE_CACHE.get(key)
            if cached and time.time() - cached[0] < AI_CACHE_TTL_SECONDS:
                _CACHE_HITS += 1
                return cached[1]
            _CACHE_MISSES += 1
            _RESPONSE_CACHE.pop(key, None)
    timeout = max(5, int(config.timeout))
    post = opener or urllib.request.urlopen
    include_temperature = model_supports_temperature(str(config.model or DEFAULT_MODEL))
    last_error: Optional[BaseException] = None
    for attempt in range(AI_REQUEST_ATTEMPTS):
        payload = build_chat_payload(config, message_list, include_temperature=include_temperature)
        request = urllib.request.Request(
            config.endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=_ai_request_headers(str(config.api_key)),
            method="POST",
        )
        try:
            result = _parse_chat_completion(_post_chat_request(request, timeout, post))
            if key:
                with _CACHE_LOCK:
                    _RESPONSE_CACHE[key] = (time.time(), result)
                    while len(_RESPONSE_CACHE) > AI_CACHE_MAX_ENTRIES:
                        _RESPONSE_CACHE.pop(next(iter(_RESPONSE_CACHE)))
            return result
        except urllib.error.HTTPError as exc:
            last_error = exc
            detail = _read_http_error_detail(exc)
            if include_temperature and _temperature_rejected(exc.code, detail):
                include_temperature = False
                continue
            if is_retryable_ai_error(exc) and attempt + 1 < AI_REQUEST_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)])
                continue
            raise RuntimeError(_format_ai_http_error(exc.code, detail)) from exc
        except Exception as exc:
            last_error = exc
            if is_retryable_ai_error(exc) and attempt + 1 < AI_REQUEST_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)])
                continue
            raise RuntimeError(format_ai_transport_error(exc)) from exc
    raise RuntimeError(format_ai_transport_error(last_error or RuntimeError("未知网络错误")))


def resolve_capability_document_path() -> Optional[str]:
    """Locate the workflow/script capability markdown shipped with the app."""
    candidates = []
    try:
        from utils.app_paths import get_app_root

        candidates.append(os.path.join(get_app_root(), "docs", CAPABILITY_DOC_NAME))
    except Exception:
        pass
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(project_root, "docs", CAPABILITY_DOC_NAME))
    seen = set()
    for path in candidates:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(path):
            return path
    return None


def load_capability_document() -> str:
    path = resolve_capability_document_path()
    if not path:
        raise FileNotFoundError("缺少产品说明文档 docs/WORKFLOW_AND_SCRIPTS.md")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError as exc:
        raise FileNotFoundError("无法读取产品说明文档 docs/WORKFLOW_AND_SCRIPTS.md") from exc
    if not text:
        raise RuntimeError("产品说明文档 docs/WORKFLOW_AND_SCRIPTS.md 为空")
    return text


def _format_condition_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " 或 ".join(str(item) for item in value)
    return str(value)


def _compact_condition(condition: Any) -> str:
    if isinstance(condition, list):
        return " 且 ".join(part for part in (_compact_condition(item) for item in condition) if part)
    if not isinstance(condition, Mapping):
        return ""
    name = condition.get("param")
    if not name:
        return ""
    operator = str(condition.get("operator") or "=").strip() or "="
    value = condition.get("value")
    if operator == "in":
        text = f"{name} 为 {_format_condition_value(value)}"
    elif operator == "!=":
        text = f"{name}≠{value}"
    elif operator == "=":
        text = f"{name}={value}"
    else:
        text = f"{name}{operator}{value}"
    extra = condition.get("and")
    if extra:
        nested = _compact_condition(extra)
        if nested:
            text = f"{text} 且 {nested}"
    return text


def _collapse_capability_text(text: Any) -> str:
    return " ".join(str(text or "").split()).strip()


def _format_option_text(options: Any) -> str:
    if isinstance(options, Mapping):
        return " | ".join(str(item) for item in options.keys())
    if isinstance(options, list) and options:
        return " | ".join(str(item) for item in options)
    return ""


def _format_param_capability(name: str, spec: Mapping[str, Any]) -> str:
    label = str(spec.get("label") or name).strip()
    param_type = str(spec.get("type") or "text").strip()
    attrs = [param_type]
    if "default" in spec and spec.get("default") not in (None, ""):
        attrs.append(f"default={spec.get('default')}")
    for key in ("min", "max", "step", "decimals"):
        if key in spec and spec.get(key) not in (None, ""):
            attrs.append(f"{key}={spec.get(key)}")
    if spec.get("required"):
        attrs.append("必填")
    if spec.get("readonly"):
        attrs.append("只读")
    if spec.get("multiline"):
        attrs.append("多行")
    line = f"{name} ({', '.join(attrs)}): {label}"
    tooltip = _collapse_capability_text(spec.get("tooltip") or spec.get("description")).rstrip("。.")
    if tooltip and tooltip != label:
        line += f"。{tooltip}"
    placeholder = _collapse_capability_text(spec.get("placeholder"))
    if placeholder:
        line += f"；占位 {placeholder}"
    file_filter = _collapse_capability_text(spec.get("file_filter") or spec.get("file_types"))
    if file_filter:
        line += f"；文件 {file_filter}"
    option_text = _format_option_text(spec.get("options", spec.get("choices")))
    if option_text:
        line += f"；选项 {option_text}"
    condition = spec.get("condition", spec.get("conditions"))
    compact = _compact_condition(condition)
    if compact:
        line += f"；当 {compact}"
    return line


def format_card_capability_catalog(task_modules: Optional[Mapping[str, Any]] = None) -> str:
    """Compact live parameter schema for every registered card type."""
    modules = task_modules
    if modules is None:
        from tasks import PRIMARY_TASK_MODULES

        modules = PRIMARY_TASK_MODULES
    lines = ["## 当前卡片参数（运行时）"]
    for task_type in modules:
        module = modules[task_type]
        getter = getattr(module, "get_params_definition", None)
        lines.append(f"### {task_type}")
        if callable(getattr(module, "check_monitor_trigger", None)):
            lines.append("- 监控节点：工作流启动时登记，不参与顺序执行。")
        else:
            lines.append("- 可执行节点。")
        if not callable(getter):
            lines.append("- （无参数定义）")
            continue
        try:
            definitions = getter()
        except Exception as exc:
            lines.append(f"- （读取参数定义失败：{exc}）")
            continue
        wrote = False
        for name, spec in (definitions or {}).items():
            if not isinstance(spec, Mapping):
                continue
            if str(name).startswith("---") or spec.get("hidden"):
                continue
            if str(spec.get("type") or "").strip().lower() in _SKIP_PARAM_TYPES:
                continue
            lines.append(f"- {_format_param_capability(str(name), spec)}")
            wrote = True
        if not wrote:
            lines.append("- （无可填写参数）")
    return "\n".join(lines)


_SCRIPT_PARAM_ALIASES = {
    "偏移横坐标": "偏移x",
    "偏移纵坐标": "偏移y",
    "随机横坐标": "随机",
    "随机纵坐标": "随机",
    "横坐标": "x",
    "纵坐标": "y",
    "按键内容": "按键",
    "起点横坐标": "x1",
    "起点纵坐标": "y1",
    "终点横坐标": "x2",
    "终点纵坐标": "y2",
    "text": "文本",
}
_SCRIPT_COMMAND_PARAM_ALIASES = {
    "相对移动": {"x": "偏移x", "y": "偏移y", "偏移横坐标": "偏移x", "偏移纵坐标": "偏移y"},
}
_SCRIPT_KWARGS_FORWARD = {
    "等图": ("找图", ()),
    "等图消失": ("找图", ()),
    "持续找图": ("找图", ("点击", "双击")),
    "等色": ("找色", ()),
    "等色消失": ("找色", ()),
    "等文字": ("找字", ()),
    "等文字消失": ("找字", ()),
    "等字库": ("找字库", ()),
    "等字库消失": ("找字库", ()),
    "等检测": ("检测", ()),
    "等检测消失": ("检测", ()),
    "持续检测": ("检测", ()),
    "按下": ("点击", ("双击", "动作", "次数", "间隔", "按住秒", "自动松开")),
    "松开": ("点击", ("双击", "动作", "次数", "间隔", "按住秒", "自动松开")),
    "按住": ("点击", ("双击", "动作", "次数", "自动松开")),
    "连点": ("点击", ("双击", "动作", "按住秒", "自动松开")),
}
_SCRIPT_ELEMENT_PARAMS = (
    ("名称", None),
    ("自动化ID", None),
    ("类名", None),
    ("控件类型", None),
    ("序号", 0),
    ("搜索深度", 30),
    ("超时", 5.0),
    ("目标", "当前"),
)
_SCRIPT_RESULT_FIELDS = (
    "通过", "类型", "内容", "分数", "阈值", "类别", "路径", "列表",
    "x", "y", "宽", "高", "左", "上", "右", "下",
    "颜色", "红", "绿", "蓝", "句柄", "返回值", "退出码",
    "标准输出", "标准错误", "进程号", "状态", "模式", "消息", "投递",
    "DPI", "缩放", "父句柄", "深度", "运行", "结果", "错误", "名字",
    "自动化ID", "类名", "控件类型", "开始时间", "完成时间",
    "头", "字节数", "地址", "勾选", "展开", "启用", "脱离屏幕", "聚焦",
    "动作", "设备号", "按钮", "摇杆X", "摇杆Y", "摇杆Z", "方向帽", "已连接",
    "DPI感知", "管理员", "DirectX", "OpenGL", "截图",
)


def _script_insert_paths(item: Mapping[str, Any]) -> List[str]:
    names = [part.strip() for part in str(item.get("name") or "").split("/") if part.strip()]
    return names or [str(item.get("name") or "").strip()]


def _is_example_param_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    if text[:1] in {'"', "'", "("}:
        return True
    stripped = text[1:] if text[:1] in "+-" else text
    return stripped.replace(".", "", 1).isdigit()


def _catalog_param_entries(item: Mapping[str, Any]) -> List[Tuple[str, Any, bool]]:
    raw = item.get("params")
    groups: Sequence[Any]
    if not raw:
        groups = ()
    elif isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
        groups = raw
    elif isinstance(raw, (list, tuple)):
        groups = (raw,)
    else:
        groups = ()
    entries: List[Tuple[str, Any, bool]] = []
    seen = set()
    for group in groups:
        for part in group:
            text = str(part).strip()
            if not text or "=" in text[:1]:
                continue
            name, has_default, default = text, False, None
            if "=" in text:
                name, raw_default = text.split("=", 1)
                name = name.strip()
                has_default = True
                default = _parse_catalog_default(raw_default.strip())
            if _is_example_param_name(name) or name in seen:
                continue
            seen.add(name)
            entries.append((name, default, has_default))
    return entries


def _parse_catalog_default(text: str) -> Any:
    value = str(text or "").strip()
    if value in {"无", "空", "None"}:
        return None
    if value in {"真", "True"}:
        return True
    if value in {"假", "False"}:
        return False
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _format_script_default(value: Any) -> str:
    if value is None:
        return "无"
    if value is True:
        return "真"
    if value is False:
        return "假"
    if value == "":
        return '""'
    if isinstance(value, str):
        return value
    return str(value)


def _public_param_name(path: str, name: str) -> str:
    mapped = _SCRIPT_COMMAND_PARAM_ALIASES.get(path, {}).get(name)
    if mapped:
        return mapped
    return _SCRIPT_PARAM_ALIASES.get(name, name)


def _script_runtime_callables() -> Dict[str, Any]:
    from task_workflow.script_commands import CommandHost
    from task_workflow.script_sandbox import (
        COMMAND_NAMES,
        _ClipboardApi,
        _DataApi,
        _EventView,
        _ExternalComponentApi,
        _HotkeyView,
        _InputDeviceView,
        _NetworkView,
        _PerformanceView,
        _ProcessView,
        _RegionApi,
        _TimerView,
        _VarsApi,
        _WindowView,
        script_assert,
        script_clamp,
        script_contains,
        script_cos,
        script_dict_get,
        script_dict_keys,
        script_dict_set,
        script_dict_values,
        script_endswith,
        script_extract_number,
        script_find,
        script_json_dump,
        script_json_parse,
        script_list_append,
        script_list_extend,
        script_list_pop,
        script_now_ms,
        script_random,
        script_replace,
        script_round,
        script_sin,
        script_slice,
        script_sort,
        script_split,
        script_sqrt,
        script_startswith,
        script_strip,
        script_type,
    )

    mapping: Dict[str, Any] = {}
    for name in COMMAND_NAMES:
        fn = getattr(CommandHost, name, None)
        if callable(fn):
            mapping[name] = fn
    mapping.update(
        {
            "开方": script_sqrt,
            "平方根": script_sqrt,
            "正弦": script_sin,
            "余弦": script_cos,
            "限制": script_clamp,
            "随机": script_random,
            "包含": script_contains,
            "截取": script_slice,
            "替换": script_replace,
            "分割": script_split,
            "时间": script_now_ms,
            "去空格": script_strip,
            "查找": script_find,
            "提取数字": script_extract_number,
            "JSON解析": script_json_parse,
            "JSON生成": script_json_dump,
            "字典获取": script_dict_get,
            "字典设置": script_dict_set,
            "列表追加": script_list_append,
            "列表合并": script_list_extend,
            "列表弹出": script_list_pop,
            "字典键": script_dict_keys,
            "字典值": script_dict_values,
            "类型": script_type,
            "断言": script_assert,
            "开头是": script_startswith,
            "结尾是": script_endswith,
            "排序": script_sort,
            "四舍五入": script_round,
        }
    )
    views = {
        "窗口": _WindowView,
        "输入设备": _InputDeviceView,
        "进程": _ProcessView,
        "网络": _NetworkView,
        "事件": _EventView,
        "热键": _HotkeyView,
        "定时器": _TimerView,
        "组件": _ExternalComponentApi,
        "数据": _DataApi,
        "性能": _PerformanceView,
        "剪贴板": _ClipboardApi,
        "变量": _VarsApi,
        "区域": _RegionApi,
    }
    for root, cls in views.items():
        for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            mapping[f"{root}.{name}"] = fn
    return mapping


def _inspect_callable_params(fn: Any) -> Tuple[List[Tuple[str, Any, bool, bool]], List[str]]:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return [], []
    entries: List[Tuple[str, Any, bool, bool]] = []
    varnames: List[str] = []
    for param in signature.parameters.values():
        if param.name in {"self", "cls"}:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            varnames.append(param.name)
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            entries.append((f"*{param.name}", None, False, True))
            continue
        has_default = param.default is not inspect.Parameter.empty
        default = param.default if has_default else None
        entries.append((param.name, default, has_default, False))
    return entries, varnames


_MOUSE_BUTTON_PATHS = frozenset(
    {
        "点击",
        "找图",
        "找色",
        "按下",
        "松开",
        "按住",
        "连点",
        "点文字",
        "点字库",
        "点元素",
        "等图",
        "等图消失",
        "持续找图",
        "等色",
        "等色消失",
    }
)


def _script_param_options(path: str, name: str) -> str:
    if name == "模式":
        return "前台驱动 | 前台脚本 | 后台消息 | 后台投递"
    if name == "按钮" or (name == "键" and path in _MOUSE_BUTTON_PATHS):
        return "左键 | 右键 | 中键"
    if name == "动作":
        if path == "按键":
            return "按下 | 松开"
        if path in _MOUSE_BUTTON_PATHS:
            return "完整点击 | 双击 | 仅按下 | 仅松开"
        return ""
    if name == "策略":
        return "最近 | 最大 | 置信度最高"
    if name == "方式" and path == "输入":
        return "仿真输入 | 粘贴"
    if name == "方向" and path == "滚轮":
        return "向上 | 向下"
    if name == "状态" and path == "窗口.元素切换":
        return "真 | 假"
    return ""


def _runtime_param_entries(path: str, runtime_map: Mapping[str, Any]) -> Tuple[List[Tuple[str, Any, bool]], bool]:
    if path in {"窗口.元素展开", "窗口.元素折叠"}:
        return [(name, default, True) for name, default in _SCRIPT_ELEMENT_PARAMS], False
    fn = runtime_map.get(path)
    if not callable(fn):
        return [], False
    raw_entries, _varnames = _inspect_callable_params(fn)
    entries: List[Tuple[str, Any, bool]] = []
    seen = set()
    has_varargs = False
    for name, default, has_default, variadic in raw_entries:
        if variadic:
            has_varargs = True
            continue
        public = _public_param_name(path, name)
        if not public or public in seen:
            continue
        if public == "目标" and path.startswith("窗口.") and default is None:
            default = "当前"
        seen.add(public)
        entries.append((public, default, has_default))
    forward = _SCRIPT_KWARGS_FORWARD.get(path)
    if forward:
        source, skipped = forward
        skip = set(skipped)
        source_entries, _ = _runtime_param_entries(source, runtime_map)
        known = {name for name, _default, _has in entries}
        for name, default, has_default in source_entries:
            if name in skip or name in known or name in {"超时", "间隔"}:
                continue
            entries.append((name, default, has_default))
    return entries, has_varargs


def _merge_script_params(path: str, item: Mapping[str, Any], runtime_map: Mapping[str, Any]) -> List[Tuple[str, Any, bool]]:
    runtime_entries, has_varargs = _runtime_param_entries(path, runtime_map)
    runtime_by_name = {name: (default, has_default) for name, default, has_default in runtime_entries}
    ordered: List[Tuple[str, Any, bool]] = []
    seen = set()

    def add(name: str, default: Any, has_default: bool) -> None:
        if not name or name in seen or name.startswith("*"):
            return
        seen.add(name)
        ordered.append((name, default, has_default))

    catalog_entries = _catalog_param_entries(item)
    if runtime_by_name:
        for name, default, has_default in catalog_entries:
            if name in runtime_by_name:
                runtime_default, runtime_has_default = runtime_by_name[name]
                add(name, runtime_default, runtime_has_default)
            elif has_varargs or path.startswith("组件."):
                add(name, default, has_default)
        for name, default, has_default in runtime_entries:
            add(name, default, has_default)
    else:
        for name, default, has_default in catalog_entries:
            add(name, default, has_default)
    return ordered


def _format_script_param(path: str, name: str, default: Any, has_default: bool) -> str:
    if name.startswith("*"):
        return name
    text = name
    if has_default:
        text += f"={_format_script_default(default)}"
    options = _script_param_options(path, name)
    if options:
        text += f"（{options}）"
    return text


def format_script_command_catalog() -> str:
    """Live custom-script commands, matching the editor command list."""
    from tasks.script_hints import KEYWORD_HINTS, _FIELD_HINTS
    from tasks.script_task import SCRIPT_INSERT_GROUPS

    runtime_map = _script_runtime_callables()
    lines = ["## 自定义脚本命令（运行时）"]
    for group in SCRIPT_INSERT_GROUPS:
        title = str(group.get("title") or "命令").strip()
        lines.append(f"### {title}")
        for item in group.get("items") or ():
            if not isinstance(item, Mapping):
                continue
            signature = str(item.get("signature") or item.get("snippet") or item.get("name") or "").strip()
            if not signature:
                continue
            signature = " | ".join(part.strip() for part in signature.splitlines() if part.strip())
            note = str(item.get("note") or "").strip()
            line = f"- {signature}"
            if note:
                line += f"：{note}"
            lines.append(line)
            paths = _script_insert_paths(item)
            if len(paths) == 1:
                params = _merge_script_params(paths[0], item, runtime_map)
                if params:
                    rendered = "；".join(
                        _format_script_param(paths[0], name, default, has_default)
                        for name, default, has_default in params
                    )
                    lines.append(f"  参数 {rendered}")
            else:
                for path in paths:
                    params = _merge_script_params(path, item, runtime_map)
                    if not params:
                        continue
                    rendered = "；".join(
                        _format_script_param(path, name, default, has_default)
                        for name, default, has_default in params
                    )
                    lines.append(f"  {path} 参数 {rendered}")
    lines.append("### 控制流")
    for name, hint in KEYWORD_HINTS.items():
        if not isinstance(hint, Mapping):
            continue
        display = " / ".join(str(item) for item in (hint.get("display") or ()) if item)
        note = str(hint.get("note") or "").strip()
        line = f"- {display or name}"
        if note:
            line += f"：{note}"
        lines.append(line)
    lines.append("### 结果字段")
    for name, text in _FIELD_HINTS.items():
        lines.append(f"- {name}：{text}")
    lines.append("- 结果对象字段：" + "、".join(f"结果.{name}" for name in _SCRIPT_RESULT_FIELDS))
    return "\n".join(lines)


def build_ai_knowledge_document(task_modules: Optional[Mapping[str, Any]] = None) -> str:
    """Full assistant knowledge: rules doc plus live card and script catalogs."""
    parts = [
        _KNOWLEDGE_HEADER,
        load_capability_document(),
        format_card_capability_catalog(task_modules),
        format_script_command_catalog(),
    ]
    text = "\n\n".join(part.strip() for part in parts if str(part or "").strip())
    if text and not text.endswith("\n"):
        return f"{text}\n"
    return text


def write_ai_knowledge_document(path: Optional[str] = None) -> str:
    """Write the knowledge document as UTF-8 and return the path."""
    if path:
        target = path
    else:
        from utils.app_paths import get_app_root

        target = os.path.join(get_app_root(), "docs", KNOWLEDGE_DOC_NAME)
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(build_ai_knowledge_document())
    return target


def _truncate_context_text(text: str, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    keep = max(0, limit - 8)
    return f"{value[:keep]}…（已截断）"


def _bounded_param_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate_context_text(value, MAX_PARAM_VALUE_CHARS)
    dumped = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(dumped) <= MAX_PARAM_VALUE_CHARS:
        return value
    return _truncate_context_text(dumped, MAX_PARAM_VALUE_CHARS)


def _format_coord(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _format_card_position(card: Mapping[str, Any]) -> str:
    if "pos_x" not in card or "pos_y" not in card:
        return ""
    return f"位置：{_format_coord(card['pos_x'])}, {_format_coord(card['pos_y'])}"


def _format_connection_type(line_type: Any) -> str:
    key = str(line_type or "").strip()
    if not key:
        raise ValueError("连线类型不能为空")
    return _LINE_TYPE_LABELS.get(key, key)


def _current_editor_view(main_window: Any) -> Tuple[Any, Any]:
    if main_window is None:
        return None, None
    tab = getattr(main_window, "workflow_tab_widget", None)
    view = None
    task = None
    if tab is not None:
        getter = getattr(tab, "get_current_workflow_view", None)
        if callable(getter):
            view = getter()
        task_id_getter = getattr(tab, "get_current_task_id", None)
        task_id = task_id_getter() if callable(task_id_getter) else None
        manager = getattr(tab, "task_manager", None)
        get_task = getattr(manager, "get_task", None) if manager is not None else None
        if callable(get_task) and task_id is not None:
            task = get_task(task_id)
    if view is None:
        view = getattr(main_window, "workflow_view", None)
    return view, task


def collect_editor_workflow_snapshot(main_window: Any = None) -> Dict[str, Any]:
    """Read the active editor canvas. Missing editor is empty; read failure is error."""
    view, task = _current_editor_view(main_window)
    serialize = getattr(view, "serialize_workflow", None)
    if view is None or not callable(serialize):
        return {"status": "empty"}
    try:
        workflow = serialize()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    if not isinstance(workflow, dict):
        return {"status": "error", "error": "当前工作流数据不是字典"}
    return {
        "status": "ok",
        "name": str(getattr(task, "name", "") or "").strip(),
        "filepath": str(getattr(task, "filepath", "") or "").strip(),
        "modified": bool(getattr(task, "modified", False)),
        "workflow": workflow,
    }


def format_editor_workflow_context(snapshot: Optional[Mapping[str, Any]] = None) -> str:
    """Compact text of the active editor workflow for the chat system prompt."""
    header = _WORKFLOW_CONTEXT_HEADER
    if not isinstance(snapshot, Mapping) or snapshot.get("status") == "empty":
        return f"{header}\n当前没有打开的工作流。"
    if snapshot.get("status") == "error":
        error = str(snapshot.get("error") or "未知错误").strip() or "未知错误"
        return f"{header}\n无法读取当前工作流：{error}"
    workflow = snapshot.get("workflow")
    if not isinstance(workflow, Mapping):
        return f"{header}\n无法读取当前工作流：工作流数据不是字典"

    cards = workflow.get("cards")
    connections = workflow.get("connections")
    if not isinstance(cards, list):
        return f"{header}\n无法读取当前工作流：卡片列表无效"
    if not isinstance(connections, list):
        return f"{header}\n无法读取当前工作流：连线列表无效"

    name = str(snapshot.get("name") or "").strip() or "未命名"
    filepath = str(snapshot.get("filepath") or "").strip() or "尚未保存到文件"
    saved = "未保存" if snapshot.get("modified") else "已保存"
    lines = [
        header,
        f"名称：{name}",
        f"文件：{filepath}",
        f"保存状态：{saved}",
        f"卡片数：{len(cards)}；连线数：{len(connections)}",
    ]
    export_cards: List[Dict[str, Any]] = []
    export_connections: List[Dict[str, Any]] = []

    for card in cards:
        if not isinstance(card, Mapping):
            return f"{header}\n无法读取当前工作流：存在无效卡片"
        card_id = card.get("id")
        task_type = str(card.get("task_type") or "").strip()
        if card_id is None or not task_type:
            return f"{header}\n无法读取当前工作流：存在无效卡片"
        custom_name = str(card.get("custom_name") or "").strip()
        title = f"### 卡片 {card_id}：{task_type}"
        if custom_name:
            title += f"（{custom_name}）"
        lines.append("")
        lines.append(title)
        try:
            position = _format_card_position(card)
        except (TypeError, ValueError):
            return f"{header}\n无法读取当前工作流：存在无效卡片"
        if position:
            lines.append(position)
        parameters = card.get("parameters")
        bounded: Dict[str, Any] = {}
        if isinstance(parameters, Mapping) and parameters:
            try:
                bounded = {str(key): _bounded_param_value(value) for key, value in parameters.items()}
                dumped = json.dumps(bounded, ensure_ascii=False, indent=2, allow_nan=False)
            except (TypeError, ValueError):
                return f"{header}\n无法读取当前工作流：存在无效卡片"
            lines.append("参数：")
            lines.append(dumped)
        export_cards.append({
            "id": card_id,
            "task_type": task_type,
            "pos_x": card.get("pos_x"),
            "pos_y": card.get("pos_y"),
            "parameters": bounded,
            "custom_name": card.get("custom_name"),
        })

    if connections:
        lines.append("")
        lines.append("### 连线")
        for item in connections:
            if not isinstance(item, Mapping):
                return f"{header}\n无法读取当前工作流：存在无效连线"
            start_id = item.get("start_card_id")
            end_id = item.get("end_card_id")
            raw_type = str(item.get("type") or "").strip()
            try:
                line_type = _format_connection_type(raw_type)
            except ValueError:
                return f"{header}\n无法读取当前工作流：存在无效连线"
            if start_id is None or end_id is None:
                return f"{header}\n无法读取当前工作流：存在无效连线"
            lines.append(f"- 卡片 {start_id} -{line_type}-> 卡片 {end_id}")
            export_connections.append({
                "start_card_id": start_id,
                "end_card_id": end_id,
                "type": raw_type,
            })

    metadata = workflow.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        try:
            dumped_metadata = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False)
        except (TypeError, ValueError):
            return f"{header}\n无法读取当前工作流：元数据无法序列化"
        lines.append("")
        lines.append("### 元数据")
        lines.append(dumped_metadata)

    export_payload: Dict[str, Any] = {
        "cards": export_cards,
        "connections": export_connections,
    }
    if isinstance(metadata, Mapping) and metadata:
        export_payload["metadata"] = dict(metadata)
    try:
        dumped_export = json.dumps(export_payload, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return f"{header}\n无法读取当前工作流：工作流 JSON 无法序列化：{exc}"
    lines.append("")
    lines.append("### 可应用的工作流JSON")
    lines.append("长参数可能已截断。修正时只把要改的项写进 ops，未改动的卡片不要整份回写。")
    lines.append(dumped_export)

    text = "\n".join(lines)
    if len(text) <= MAX_WORKFLOW_CONTEXT_CHARS:
        return text
    return _truncate_context_text(text, MAX_WORKFLOW_CONTEXT_CHARS)


def editor_workflow_context(main_window: Any = None) -> str:
    return format_editor_workflow_context(collect_editor_workflow_snapshot(main_window))


def chat_system_prompt(
    task_modules: Optional[Mapping[str, Any]] = None,
    *,
    workflow_context: Optional[str] = None,
) -> str:
    parts = [_CHAT_SYSTEM_PROMPT, build_ai_knowledge_document(task_modules)]
    context = str(workflow_context or "").strip()
    if context:
        parts.append(context)
    return "\n\n".join(parts)


def build_ai_chat_messages(
    system: str,
    history: Iterable[Mapping[str, str]],
) -> list[dict[str, str]]:
    """System + recent turns."""
    messages = [{"role": "system", "content": str(system or "")}]
    for item in history:
        role = str(item.get("role") or "user")
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "")[:MAX_PROMPT_CHARS]
        if content:
            messages.append({"role": role, "content": content})
    return messages
