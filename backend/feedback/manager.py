# backend/feedback/manager.py
"""用户反馈管理：手动反馈 + 自动熵筛选候选。"""

from memory import database
from .entropy import compute_entropy_score


def save_feedback(context: dict, rating: str) -> bool:
    """手动反馈，保持原行为，rating 只能是 good/bad。"""
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
            entropy_score=None,
            value_tier="manual",
        )
        return True
    except Exception as e:
        print(f"[Feedback] ❌ 手动反馈写入失败: {e}", flush=True)
        return False


def save_auto_candidate(context: dict) -> dict:
    """
    每轮对话都调用：先算熵，再走筛网。
    返回打分结果，方便调用方打日志；低价值/丢弃的不写库。
    """
    um = context.get("user_message", "") or ""
    ar = context.get("ai_reply", "") or ""

    result = compute_entropy_score(um, ar)
    score = result["score"]
    tier = result["tier"]

    # 筛网：drop 和 low 都不进候选池
    if tier in ("drop", "low"):
        print(
            f"[Feedback] 🧹 筛除 tier={tier} score={score:.3f} "
            f"| {um[:40]!r}",
            flush=True,
        )
        return result

    try:
        database.insert_feedback(
            message_id=context.get("message_id", ""),
            session_id=context.get("session_id", ""),
            user_id=context.get("user_id", "default"),
            user_message=um,
            ai_reply=ar,
            emotion=context.get("emotion", ""),
            tts_emotion=context.get("tts_emotion", ""),
            rating="auto",
            entropy_score=score,
            value_tier=tier,
        )
        print(
            f"[Feedback] ✅ 候选 tier={tier} score={score:.3f} "
            f"metrics={result['metrics']} | {um[:40]!r}",
            flush=True,
        )
    except Exception as e:
        print(f"[Feedback] ❌ 自动候选写入失败: {e}", flush=True)

    return result


def get_feedback_stats() -> dict:
    try:
        return database.get_feedback_stats()
    except Exception as e:
        print(f"[Feedback] ❌ 读取统计失败: {e}", flush=True)
        return {"total": 0, "good": 0, "bad": 0}