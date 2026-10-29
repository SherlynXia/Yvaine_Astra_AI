# backend/feedback/manager.py
"""用户反馈管理：写入 SQLite feedback 表"""

from datetime import datetime
from memory import database


def save_feedback(context: dict, rating: str) -> bool:
    """
    context: message_id, session_id, user_message, ai_reply, emotion, tts_emotion
    rating: 'good' | 'bad'
    """
    if rating not in ("good", "bad"):
        return False

    try:
        database.insert_feedback(
            message_id=context.get("message_id", ""),
            session_id=context.get("session_id", ""),
            user_id=context.get("user_id", "default"),
            user_message=context.get("user_message", ""),
            ai_reply=context.get("ai_reply", ""),
            emotion=context.get("emotion", ""),
            tts_emotion=context.get("tts_emotion", ""),
            rating=rating,
        )
        return True
    except Exception as e:
        print(f"[Feedback] ❌ 写入失败: {e}", flush=True)
        return False


def get_feedback_stats() -> dict:
    try:
        return database.get_feedback_stats()
    except Exception as e:
        print(f"[Feedback] ❌ 读取统计失败: {e}", flush=True)
        return {"total": 0, "good": 0, "bad": 0}