# backend/feedback_manager.py
"""用户反馈管理器 — 记录点赞/点踩的对话，用于未来训练专属模型"""

import json
from pathlib import Path
from datetime import datetime
import threading

# 数据文件位置
DATA_DIR = Path(__file__).parent / "data"
FEEDBACK_FILE = DATA_DIR / "feedback.jsonl"

# 确保目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 文件写入锁（防止多线程并发写坏 JSONL）
_write_lock = threading.Lock()


def save_feedback(context: dict, rating: str) -> bool:
    """
    保存一条评分反馈
    
    context 应包含：
        message_id, session_id, user_message, ai_reply, emotion, tts_emotion
    rating: 'good' 或 'bad'
    """
    if rating not in ("good", "bad"):
        return False

    record = {
        **context,
        "rating": rating,
        "rated_at": datetime.now().isoformat(),
    }

    try:
        with _write_lock:
            with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        print(f"[Feedback] ❌ 写入失败: {e}", flush=True)
        return False


def get_feedback_stats() -> dict:
    """返回反馈统计（给前端展示用）"""
    if not FEEDBACK_FILE.exists():
        return {"total": 0, "good": 0, "bad": 0}

    total = good = bad = 0
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    total += 1
                    if record.get("rating") == "good":
                        good += 1
                    elif record.get("rating") == "bad":
                        bad += 1
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[Feedback] ❌ 读取统计失败: {e}", flush=True)

    return {"total": total, "good": good, "bad": bad}