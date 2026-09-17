"""Local AI assistant conversation store. API keys are never written here."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from utils.app_paths import get_ai_sessions_path

MAX_SESSIONS = 40
MAX_MESSAGES = 80
DEFAULT_TITLE = "新对话"


def _now() -> float:
    return time.time()


def empty_session(*, title: str = DEFAULT_TITLE) -> Dict[str, Any]:
    stamp = _now()
    return {
        "id": uuid.uuid4().hex,
        "title": title or DEFAULT_TITLE,
        "created_at": stamp,
        "updated_at": stamp,
        "messages": [],
    }


def empty_store() -> Dict[str, Any]:
    session = empty_session()
    return {"current_id": session["id"], "sessions": [session]}


def _normalize_message(raw: Any) -> Optional[Dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or "").strip()
    content = str(raw.get("content") or "")
    if role not in {"user", "assistant"} or not content.strip():
        return None
    return {"role": role, "content": content}


def _normalize_session(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    session_id = str(raw.get("id") or "").strip() or uuid.uuid4().hex
    title = str(raw.get("title") or DEFAULT_TITLE).strip() or DEFAULT_TITLE
    messages = []
    for item in raw.get("messages") or []:
        message = _normalize_message(item)
        if message:
            messages.append(message)
        if len(messages) >= MAX_MESSAGES:
            break
    return {
        "id": session_id,
        "title": title,
        "created_at": float(raw.get("created_at") or _now()),
        "updated_at": float(raw.get("updated_at") or _now()),
        "messages": messages,
    }


def normalize_store(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return empty_store()
    sessions = []
    seen = set()
    for item in raw.get("sessions") or []:
        session = _normalize_session(item)
        if session is None or session["id"] in seen:
            continue
        seen.add(session["id"])
        sessions.append(session)
        if len(sessions) >= MAX_SESSIONS:
            break
    if not sessions:
        return empty_store()
    sessions.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    current_id = str(raw.get("current_id") or "")
    if current_id not in {item["id"] for item in sessions}:
        current_id = sessions[0]["id"]
    return {"current_id": current_id, "sessions": sessions}


def load_ai_sessions(path: Optional[str] = None) -> Dict[str, Any]:
    target = path or get_ai_sessions_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return normalize_store(json.load(handle))
    except FileNotFoundError:
        return empty_store()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return empty_store()


def save_ai_sessions(store: Dict[str, Any], path: Optional[str] = None) -> None:
    target = path or get_ai_sessions_path()
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = normalize_store(store)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def get_session(store: Dict[str, Any], session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    wanted = str(session_id or store.get("current_id") or "")
    for session in store.get("sessions") or []:
        if session.get("id") == wanted:
            return session
    return None


def set_current_session(store: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    if get_session(store, session_id) is None:
        return store
    store["current_id"] = session_id
    return store


def create_session(store: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    session = empty_session(**kwargs)
    sessions = list(store.get("sessions") or [])
    sessions.insert(0, session)
    store["sessions"] = sessions[:MAX_SESSIONS]
    store["current_id"] = session["id"]
    return session


def delete_session(store: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    sessions = [item for item in (store.get("sessions") or []) if item.get("id") != session_id]
    if not sessions:
        replacement = empty_session()
        store["sessions"] = [replacement]
        store["current_id"] = replacement["id"]
        return replacement
    store["sessions"] = sessions
    if store.get("current_id") == session_id:
        store["current_id"] = sessions[0]["id"]
    return get_session(store)


def rename_session(store: Dict[str, Any], session_id: str, title: str) -> Optional[Dict[str, Any]]:
    session = get_session(store, session_id)
    if session is None:
        return None
    session["title"] = str(title or "").strip() or DEFAULT_TITLE
    session["updated_at"] = _now()
    return session


def append_message(store: Dict[str, Any], session_id: str, role: str, content: str) -> Optional[Dict[str, Any]]:
    session = get_session(store, session_id)
    message = _normalize_message({"role": role, "content": content})
    if session is None or message is None:
        return None
    session["messages"] = (list(session.get("messages") or []) + [message])[-MAX_MESSAGES:]
    session["updated_at"] = _now()
    if session.get("title") in {"", DEFAULT_TITLE} and message["role"] == "user":
        session["title"] = suggest_session_title(message["content"])
    return session


def suggest_session_title(text: str, *, max_length: int = 16) -> str:
    first = str(text or "").splitlines()[0].strip()
    first = " ".join(first.split())
    if not first:
        return DEFAULT_TITLE
    return first[:max_length]


def chat_history(session: Optional[Dict[str, Any]], *, limit: int = 8) -> List[Dict[str, str]]:
    messages = list((session or {}).get("messages") or [])
    history = []
    for item in messages[-max(1, int(limit)):]:
        message = _normalize_message(item)
        if message:
            history.append(message)
    return history
