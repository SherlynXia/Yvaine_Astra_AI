# backend/memory/user_manager.py
"""用户管理：当前为登录选择模式，未来接声纹识别"""

import uuid
from datetime import datetime
from . import database

DEFAULT_USER_ID = "default"
DEFAULT_USER_NAME = "主人"

# 过渡期：session_id -> user_id 映射
# 未来声纹上线后，这个映射仍保留，作为"声纹匹配失败时的回退"
_session_users: dict[str, str] = {}


async def identify_user(
    audio_data: bytes | None = None,
    session_id: str = "",
) -> str:
    """
    识别当前用户。

    现在：返回 session 绑定的用户，默认 default。
    未来：audio_data 有值时先做声纹匹配，匹配失败回退到 session 绑定。
    """
    # TODO(声纹): if audio_data:
    #     user_id = await _match_voiceprint(audio_data)
    #     if user_id:
    #         return user_id
    return _session_users.get(session_id, DEFAULT_USER_ID)


def bind_session(session_id: str, user_id: str) -> None:
    """登录时调用：把 session 绑定到用户"""
    _session_users[session_id] = user_id


def unbind_session(session_id: str) -> None:
    """断开连接时清理"""
    _session_users.pop(session_id, None)


def get_current_user(user_id: str = DEFAULT_USER_ID) -> dict:
    """获取或创建用户"""
    return database.get_or_create_user(user_id, name=DEFAULT_USER_NAME if user_id == DEFAULT_USER_ID else "")


def list_users() -> list[dict]:
    """给前端登录界面用"""
    conn = database.get_conn()
    rows = conn.execute(
        "SELECT user_id, name, last_seen_at, intimacy FROM users ORDER BY last_seen_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def create_user(name: str) -> dict:
    """新建用户，返回 user_id"""
    user_id = str(uuid.uuid4())
    database.get_or_create_user(user_id, name=name)
    return {"user_id": user_id, "name": name}