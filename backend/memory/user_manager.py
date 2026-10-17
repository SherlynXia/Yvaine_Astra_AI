# backend/memory/user_manager.py
"""用户管理 + 声纹识别接口（当前只有默认用户）"""

from . import database

DEFAULT_USER_ID = "default"
DEFAULT_USER_NAME = "主人"


async def identify_user(audio_data: bytes | None = None) -> str:
    """
    声纹识别 → 返回 user_id。
    当前版本：始终返回默认用户。
    未来：提取声纹特征，匹配 users 表的 voiceprint。
    """
    return DEFAULT_USER_ID


def get_current_user(user_id: str = DEFAULT_USER_ID) -> dict:
    return database.get_or_create_user(user_id, name=DEFAULT_USER_NAME)