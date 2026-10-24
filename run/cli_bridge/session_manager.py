# -*- coding: utf-8 -*-
import json
import os
import time
from typing import Optional, Dict, Any


SESSION_FILE = os.path.join("data", "cli_bridge_sessions.json")


def _load_all_sessions() -> Dict[str, Any]:
    try:
        if not os.path.exists(SESSION_FILE):
            return {}
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except (OSError, ValueError):
        return {}


def _save_all_sessions(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def get_session_id(key: str) -> Optional[str]:
    """获取指定 key 的 session_id，兼容旧版的直接字符串存储与新版的字典存储"""
    if not key:
        return None
    sessions = _load_all_sessions()
    item = sessions.get(key)
    if isinstance(item, str):
        return item
    elif isinstance(item, dict):
        return item.get("session_id")
    return None


def get_session_info(key: str) -> Optional[Dict[str, Any]]:
    """获取指定 key 的完整 session 信息"""
    if not key:
        return None
    sessions = _load_all_sessions()
    item = sessions.get(key)
    if isinstance(item, str):
        return {"session_id": item, "updated_at": None}
    elif isinstance(item, dict):
        return item
    return None


def save_session(key: str, session_id: str, prompt: str = "") -> None:
    """保存或更新 session"""
    if not key or not session_id:
        return
    sessions = _load_all_sessions()
    now = time.time()
    existing = sessions.get(key)
    created_at = existing.get("created_at", now) if isinstance(existing, dict) else now

    sessions[key] = {
        "session_id": session_id,
        "created_at": created_at,
        "updated_at": now,
        "last_prompt": prompt[:100] if prompt else ""
    }
    _save_all_sessions(sessions)


def clear_session(key: str) -> bool:
    """清除指定 key 的 session"""
    if not key:
        return False
    sessions = _load_all_sessions()
    if key in sessions:
        del sessions[key]
        _save_all_sessions(sessions)
        return True
    return False


def clear_all_sessions_for_user(user_id: int) -> int:
    """清除指定用户所有的 session"""
    sessions = _load_all_sessions()
    prefix = f"{user_id}:"
    keys_to_remove = [k for k in sessions if k.startswith(prefix)]
    for k in keys_to_remove:
        del sessions[k]
    if keys_to_remove:
        _save_all_sessions(sessions)
    return len(keys_to_remove)
