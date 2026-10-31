# backend/memory/lifecycle.py
"""记忆生命周期：只作用于 user_memories（TTL + 衰减）；ai_reflections / ai_behaviors 不衰减"""

import asyncio
from datetime import datetime
from . import database, vector_store
from .reflection import generate_reflections

# 只对 user_memories 生效
TYPE_TTL_DAYS = {
    "fact": None,
    "event": 90,
    "emotion": 30,
}
IMPORTANCE_PROTECT = 0.8

DECAY_IDLE_DAYS = 7
DECAY_RATE = 0.85
DECAY_FLOOR_MAP = {
    "fact": 0.5,
    "event": 0.2,
    "emotion": 0.1,
}


def apply_decay(meta: dict) -> tuple[float, str | None]:
    mtype = meta.get("type", "fact")
    base = meta.get("importance", 0.5)
    created = meta.get("created_at") or ""
    last_access = meta.get("last_accessed") or created
    last_decay = meta.get("decay_applied_at") or created

    start = max(last_access, last_decay)
    if not start:
        return base, None

    try:
        start_dt = datetime.fromisoformat(start)
    except Exception:
        return base, None

    days = (datetime.now() - start_dt).days
    if days < DECAY_IDLE_DAYS:
        return base, None

    periods = days // DECAY_IDLE_DAYS
    floor = DECAY_FLOOR_MAP.get(mtype, 0.2)
    new_imp = max(floor, round(base * (DECAY_RATE ** periods), 3))

    if new_imp >= base:
        return base, None
    return new_imp, datetime.now().isoformat()


def solidify_decay() -> int:
    conn = database.get_conn()
    rows = conn.execute(
        "SELECT memory_id, type, importance, created_at, last_accessed, decay_applied_at FROM user_memories"
    ).fetchall()

    updates = []
    for r in rows:
        new_imp, new_at = apply_decay(dict(r))
        if new_at is not None:
            updates.append((new_imp, new_at, r["memory_id"]))

    if updates:
        conn.executemany(
            "UPDATE user_memories SET importance = ?, decay_applied_at = ? WHERE memory_id = ?",
            updates,
        )
        conn.commit()
        print(f"[Memory] 📉 衰减写回: {len(updates)} 条", flush=True)
    return len(updates)


def run_lifecycle_once() -> dict:
    conn = database.get_conn()
    now = datetime.now()

    purged = database.purge_old_conversations(days=3)
    if purged:
        print(f"[Memory] 🧹 清理旧对话历史: {purged} 条", flush=True)

    # 新增：清理 expires_at 已过期的事件（无条件删，不看 importance）
    expired_ids = database.purge_expired_memories()
    for mid in expired_ids:
        vector_store.delete_user_memory(mid)
    if expired_ids:
        print(f"[Memory] 🧹 清理过期事件: {len(expired_ids)} 条", flush=True)

    rows = conn.execute(
        "SELECT memory_id, type, importance, last_accessed, created_at FROM user_memories"
    ).fetchall()

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
        ttl = TYPE_TTL_DAYS.get(mtype)
        if ttl is not None and days_idle > ttl and importance < IMPORTANCE_PROTECT:
            conn.execute("DELETE FROM user_memories WHERE memory_id = ?", (mid,))
            vector_store.delete_user_memory(mid)
            deleted += 1
            print(f"[Memory] 🗑️ 过期清理: [{mtype}] imp={importance:.2f} idle={days_idle}d", flush=True)

    conn.commit()
    decayed = solidify_decay()
    return {"deleted": deleted, "decayed": decayed, "purged": purged, "expired": len(expired_ids)}


async def lifecycle_loop(provider, interval_hours: float = 6.0):
    await asyncio.sleep(60)

    try:
        await asyncio.to_thread(run_lifecycle_once)
    except Exception as e:
        print(f"[Memory] ⚠️ 启动生命周期失败: {e}", flush=True)

    while True:
        try:
            result = await asyncio.to_thread(run_lifecycle_once)
            if result["deleted"] or result["decayed"] or result["expired"] or result.get("archived_topics"):
                print(
                    f"[Memory] 🧹 生命周期: 清理 {result['deleted']}，衰减 {result['decayed']}，"
                    f"过期 {result['expired']}，归档话题 {result.get('archived_topics', 0)}",
                    flush=True,
                )

            # 每轮都尝试反思，should_reflect 内部按「自上次反思后的新增量」判断，天然幂等
            users = database.get_conn().execute(
                "SELECT DISTINCT user_id FROM user_memories WHERE user_id != 'ai_self'"
            ).fetchall()
            for (uid,) in users:
                try:
                    await generate_reflections(provider, uid)
                except Exception as e:
                    print(f"[Reflection] ⚠️ 用户 {uid[:8]} 反思失败: {e}", flush=True)

        except Exception as e:
            print(f"[Memory] ⚠️ 生命周期失败: {e}", flush=True)

        await asyncio.sleep(interval_hours * 3600)