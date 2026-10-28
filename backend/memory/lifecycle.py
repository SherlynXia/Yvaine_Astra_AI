# backend/memory/lifecycle.py
"""记忆生命周期：TTL 清理 + 衰减写回 + 反思调度"""

import asyncio
from datetime import datetime
from . import database, vector_store
from .reflection import generate_reflections

# ========== TTL ==========
TYPE_TTL_DAYS = {
    "fact": None,
    "event": 90,
    "emotion": 30,
    "reflection": None,
    "invalidated": None,
}
IMPORTANCE_PROTECT = 0.8

# ========== 衰减 ==========
DECAY_IDLE_DAYS = 7
DECAY_RATE = 0.85
DECAY_FLOOR_MAP = {
    "fact": 0.5,
    "reflection": 0.6,
    "event": 0.2,
    "emotion": 0.1,
}


def apply_decay(meta: dict) -> tuple[float, str | None]:
    """
    计算衰减后的 importance。
    返回 (新值, 新 decay_applied_at)；不需要衰减时返回 (原值, None)。
    幂等：连续调用两次，第二次返回 None。
    """
    mtype = meta.get("type", "fact")
    if mtype == "invalidated":
        return 0.0, None

    base = meta.get("importance", 0.5)
    created = meta.get("created_at") or ""
    last_access = meta.get("last_accessed") or created
    last_decay = meta.get("decay_applied_at") or created

    # 衰减起点 = 上次访问 和 上次衰减 中较晚的那个
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
    """把所有需要衰减的记忆写回库，返回更新条数"""
    conn = database.get_conn()
    rows = conn.execute(
        "SELECT memory_id, type, importance, created_at, last_accessed, decay_applied_at "
        "FROM memories WHERE type != 'invalidated'"
    ).fetchall()

    updates = []
    for r in rows:
        new_imp, new_at = apply_decay(dict(r))
        if new_at is not None:
            updates.append((new_imp, new_at, r["memory_id"]))

    if updates:
        conn.executemany(
            "UPDATE memories SET importance = ?, decay_applied_at = ? WHERE memory_id = ?",
            updates,
        )
        conn.commit()
        print(f"[Memory] 📉 衰减写回: {len(updates)} 条", flush=True)

    return len(updates)


def run_lifecycle_once() -> dict:
    """TTL 清理 + 衰减写回，返回 {deleted, decayed}"""
    conn = database.get_conn()
    now = datetime.now()

    rows = conn.execute(
        "SELECT memory_id, type, importance, last_accessed, created_at FROM memories"
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
            conn.execute("DELETE FROM memories WHERE memory_id = ?", (mid,))
            try:
                vector_store.delete_vector(mid)
            except Exception:
                pass
            deleted += 1
            print(f"[Memory] 🗑️ 过期清理: [{mtype}] imp={importance:.2f} idle={days_idle}d", flush=True)

    conn.commit()

    decayed = solidify_decay()
    return {"deleted": deleted, "decayed": decayed}


async def lifecycle_loop(provider, interval_hours: float = 6.0):
    # 启动后先等 60 秒，避开初始化高峰
    await asyncio.sleep(60)

    # 启动时立即补一次（补上关闭期间的衰减）
    try:
        await asyncio.to_thread(run_lifecycle_once)
    except Exception as e:
        print(f"[Memory] ⚠️ 启动生命周期失败: {e}", flush=True)

    reflection_counter = 0
    while True:
        try:
            result = await asyncio.to_thread(run_lifecycle_once)
            if result["deleted"] or result["decayed"]:
                print(
                    f"[Memory] 🧹 生命周期: 清理 {result['deleted']}，衰减 {result['decayed']}",
                    flush=True,
                )

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