# backend/memory/lifecycle.py
"""记忆生命周期：衰减与自动清理"""

import asyncio
from datetime import datetime
from . import database, vector_store
from .reflection import generate_reflections

# 各类型的清理阈值（天数）
# None 表示永不自动删除
TYPE_TTL_DAYS = {
    "fact": None,        # 事实（姓名、喜好）永久保留
    "event": 90,         # 事件 90 天后过期
    "emotion": 30,       # 情绪 30 天后过期
    "reflection": None,  # 反思长期保留
}

# 重要度保护线：>= 此值的记忆永不自动删除
IMPORTANCE_PROTECT = 0.8

# 衰减：超过 N 天未访问，重要度每次 × 0.9
DECAY_IDLE_DAYS = 30
DECAY_RATE = 0.9
DECAY_FLOOR = 0.2


def run_lifecycle_once() -> dict:
    """跑一次生命周期维护，返回 {decayed, deleted}"""
    conn = database.get_conn()
    now = datetime.now()

    rows = conn.execute(
        "SELECT memory_id, type, importance, last_accessed, created_at FROM memories"
    ).fetchall()

    decayed = 0
    deleted = 0

    for r in rows:
        mid = r["memory_id"]
        mtype = r["type"]
        importance = r["importance"]
        last_accessed = r["last_accessed"] or r["created_at"]

        try:
            last = datetime.fromisoformat(last_accessed)
        except Exception:
            continue

        days_idle = (now - last).days

        # 1. 清理：按类型 TTL
        ttl = TYPE_TTL_DAYS.get(mtype)
        if (
            ttl is not None
            and days_idle > ttl
            and importance < IMPORTANCE_PROTECT
        ):
            conn.execute("DELETE FROM memories WHERE memory_id = ?", (mid,))
            try:
                vector_store.delete_vector(mid)
            except Exception:
                pass
            deleted += 1
            print(f"[Memory] 🗑️ 过期清理: [{mtype}] imp={importance:.2f} idle={days_idle}d", flush=True)
            continue

        # 2. 衰减：长期未访问的降权
        DECAY_EXEMPT_TYPES = {"fact", "reflection", "invalidated"}
        if (
            mtype not in DECAY_EXEMPT_TYPES
            and days_idle > DECAY_IDLE_DAYS
            and importance > DECAY_FLOOR
        ):
            new_imp = max(DECAY_FLOOR, round(importance * DECAY_RATE, 3))
            if new_imp < importance:
                conn.execute(
                    "UPDATE memories SET importance = ? WHERE memory_id = ?",
                    (new_imp, mid),
                )
                decayed += 1

    conn.commit()
    return {"decayed": decayed, "deleted": deleted}


async def lifecycle_loop(provider, interval_hours: float = 6.0):
    await asyncio.sleep(60)
    reflection_counter = 0

    while True:
        try:
            result = await asyncio.to_thread(run_lifecycle_once)
            if result["decayed"] or result["deleted"]:
                print(f"[Memory] 🧹 生命周期: 衰减 {result['decayed']}，清理 {result['deleted']}", flush=True)

            # 每 28 次（约 7 天，6h × 28）跑一次反思
            reflection_counter += 1
            if reflection_counter >= 28:
                reflection_counter = 0
                users = database.get_conn().execute(
                    "SELECT DISTINCT user_id FROM memories"
                ).fetchall()
                for (uid,) in users:
                    await generate_reflections(provider, uid)

        except Exception as e:
            print(f"[Memory] ⚠️ 生命周期失败: {e}", flush=True)

        await asyncio.sleep(interval_hours * 3600)