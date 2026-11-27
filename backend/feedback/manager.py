# backend/feedback/manager.py
"""用户反馈管理：手动反馈 + 自动熵筛选候选。"""

from memory import database
from .entropy import compute_entropy_score


def save_feedback(context: dict, rating: str) -> bool:
    """人工评价：有自动行就 UPDATE manual_rating，没有就 INSERT 一行"""
    if rating not in ("good", "bad"):
        return False
    message_id = context.get("message_id", "")
    if not message_id:
        return False
    try:
        conn = database.get_conn()
        row = conn.execute(
            "SELECT id FROM feedback WHERE message_id = ?", (message_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE feedback SET manual_rating = ? WHERE id = ?",
                (rating, row["id"]),
            )
            conn.commit()
            print(f"[Feedback] ✅ 人工标记 {rating}: {message_id[:8]}", flush=True)
            return True

        # 兜底：自动行没写（服务重启期间），补插一行
        metrics = compute_entropy_score(
            context.get("user_message", ""), context.get("ai_reply", "")
        )
        database.insert_feedback(
            message_id=message_id,
            session_id=context.get("session_id", ""),
            user_id=context.get("user_id", "default"),
            user_message=context.get("user_message", ""),
            ai_reply=context.get("ai_reply", ""),
            emotion=context.get("emotion", ""),
            tts_emotion=context.get("tts_emotion", ""),
            entropy_score=metrics["score"],
            value_tier=metrics["tier"],
            manual_rating=rating,
        )
        print(f"[Feedback] ✅ 人工评价补插 {rating}: {message_id[:8]}", flush=True)
        return True
    except Exception as e:
        print(f"[Feedback] ❌ 人工反馈写入失败: {e}", flush=True)
        return False


def save_auto_candidate(context: dict) -> dict:
    """每轮对话都打分并写库，low/drop 也写，供人工救回"""
    um = context.get("user_message", "") or ""
    ar = context.get("ai_reply", "") or ""
    if not um.strip():
        return {"score": 0.0, "tier": "drop", "metrics": {}}

    result = compute_entropy_score(um, ar)
    tier = result["tier"]
    if tier == "drop":
        tier = "low"   # 统一成 low，避免 value_tier 出现 drop

    try:
        database.insert_feedback(
            message_id=context.get("message_id", ""),
            session_id=context.get("session_id", ""),
            user_id=context.get("user_id", "default"),
            user_message=um,
            ai_reply=ar,
            emotion=context.get("emotion", ""),
            tts_emotion=context.get("tts_emotion", ""),
            entropy_score=result["score"],
            value_tier=tier,
            manual_rating=None,
        )
        print(
            f"[Feedback] 📝 {tier} score={result['score']:.3f} | {um[:40]!r}",
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