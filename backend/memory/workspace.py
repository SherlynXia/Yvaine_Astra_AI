# backend/memory/workspace.py
"""工作记忆：话题容器 + 素材条目，生命周期由对话续期"""

import json
import re
from pathlib import Path

from . import database, vector_store
from llm.base import LLMProvider

# 去重阈值（比 user_memories 的 0.08 宽松，素材允许微调）
DEDUP_DIST = 0.1
# 默认话题 TTL
DEFAULT_TTL_DAYS = 7
# 注入时最多展示几个 active 话题
MAX_INJECT_TOPICS = 2
# 每个话题注入最多几条最近素材
MAX_INJECT_ITEMS = 3

PENDING_JSON = Path(__file__).parent.parent / "data" / "pending_workspace.json"


_MATCH_PROMPT = """你是话题归类助手。下面是用户当前的活跃话题列表，以及一条新的项目素材。

【已有话题】
{topics_text}

【新素材】
{content}

【话题提示（可能为空）】
{topic_hint}

判断这条素材属于哪个已有话题，还是新话题。

【输出格式】
严格 JSON，二选一：
{{"topic_id": "已有话题的 topic_id"}}
或
{{"new_topic": {{"title": "简短话题名（15字以内）", "ttl_days": 7}}}}

【判断准则】
- 素材属于某个已有话题的核心内容 → 归入该话题
- 素材是全新方向，和现有话题无明显关联 → 新建话题
- ttl_days：短期话题 7，中期项目 30，长期项目 90

JSON："""


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def _match_or_create_topic(
    provider: LLMProvider,
    user_id: str,
    content: str,
    topic_hint: str = "",
) -> str:
    """返回话题 topic_id。没有 active 话题时直接新建。"""
    topics = database.list_active_topics(user_id, limit=10)

    # 无话题 → 直接新建，省一次 LLM 调用
    if not topics:
        title = (topic_hint or content)[:15]
        tid = database.insert_workspace_topic(user_id=user_id, title=title, summary=content[:100])
        print(f"[Workspace] 🆕 新建话题: {title}", flush=True)
        return tid

    topics_text = "\n".join(
        f"- [{t['topic_id'][:8]}] {t['title']} | {t['summary'][:60]}"
        for t in topics
    )
    prompt = _MATCH_PROMPT.format(
        topics_text=topics_text, content=content, topic_hint=topic_hint or "（无）"
    )

    try:
        raw = await provider.chat([{"role": "user", "content": prompt}], temperature=0.2)
    except Exception as e:
        print(f"[Workspace] ⚠️ 话题匹配失败，新建话题: {e}", flush=True)
        title = (topic_hint or content)[:15]
        return database.insert_workspace_topic(user_id=user_id, title=title, summary=content[:100])

    result = _parse_json(raw or "")
    if not result:
        title = (topic_hint or content)[:15]
        return database.insert_workspace_topic(user_id=user_id, title=title, summary=content[:100])

    # 匹配到已有话题：LLM 可能返回前缀 id，模糊匹配
    if "topic_id" in result:
        prefix = result["topic_id"].strip()
        for t in topics:
            if t["topic_id"].startswith(prefix) or t["topic_id"] == prefix:
                return t["topic_id"]

    # 新建
    new = result.get("new_topic", {})
    title = str(new.get("title", topic_hint or content[:15]))[:20]
    ttl = int(new.get("ttl_days", DEFAULT_TTL_DAYS))
    tid = database.insert_workspace_topic(
        user_id=user_id, title=title, summary=content[:100], ttl_days=ttl
    )
    print(f"[Workspace] 🆕 新建话题: {title} (ttl={ttl}d)", flush=True)
    return tid


async def record_item(
    provider: LLMProvider,
    user_id: str,
    content: str,
    item_type: str = "setting",
    topic_hint: str = "",
) -> str | None:
    """记录一条工作记忆素材。返回 item_id，去重时返回 None。"""
    if not content or len(content) < 3:
        return None

    topic_id = await _match_or_create_topic(provider, user_id, content, topic_hint)

    # 话题内去重
    similar = vector_store.query_workspace_items(content, topic_id, top_k=1)
    if similar and similar[0]["distance"] < DEDUP_DIST:
        existing_id = similar[0]["memory_id"]
        database.touch_workspace_item(existing_id)
        database.touch_workspace_topic(topic_id)
        print(f"[Workspace] ⏭️ 素材重复，续期 (dist={similar[0]['distance']:.3f})", flush=True)
        return None

    item_id = database.insert_workspace_item(topic_id, content, item_type)
    vector_store.add_workspace_item(item_id, content, topic_id, item_type)
    print(f"[Workspace] 📝 记录素材 [{item_type}]: {content[:50]}", flush=True)
    return item_id


def get_workspace_block(user_id: str) -> str:
    """生成注入 retriever 的「当前工作话题」文本。无活跃话题时返回空串。"""
    topics = database.list_active_topics(user_id, limit=MAX_INJECT_TOPICS)
    if not topics:
        return ""

    lines = ["【当前工作话题】"]
    for t in topics:
        items = database.list_workspace_items(t["topic_id"], limit=50)
        recent = items[-MAX_INJECT_ITEMS:] if items else []
        lines.append(f"\n▸ {t['title']}（{len(items)} 条素材）")
        if t["summary"]:
            lines.append(f"  摘要：{t['summary'][:80]}")
        if recent:
            lines.append("  最近素材：")
            for it in recent:
                lines.append(f"    - {it['content'][:60]}")
    return "\n".join(lines)


def archive_stale_topics() -> int:
    """归档超过 TTL 未提及的话题，返回归档数。"""
    stale = database.list_stale_topics()
    for t in stale:
        database.archive_workspace_topic(t["topic_id"])
        print(f"[Workspace] 📦 归档话题: {t['title']} (idle>{t['ttl_days']}d)", flush=True)
    return len(stale)


# ========== 迁移 pending_workspace.json ==========

async def import_pending(provider: LLMProvider) -> int:
    """把 migrate_cleanup 导出的 pending_workspace.json 迁入 workspace 表"""
    if not PENDING_JSON.exists():
        print("[Workspace] ⏭️ 无 pending_workspace.json，跳过", flush=True)
        return 0

    try:
        pending = json.loads(PENDING_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Workspace] ⚠️ 读取 pending_workspace.json 失败: {e}", flush=True)
        return 0

    if not pending:
        return 0

    imported = 0
    for entry in pending:
        content = entry.get("content", "").strip()
        user_id = entry.get("user_id", "")
        if not content or not user_id:
            continue
        item_type = "setting"
        note = entry.get("note", "")
        # note 里带"构思"→ idea，"设定"→ setting
        if "构思" in note or "想法" in note:
            item_type = "idea"
        iid = await record_item(provider, user_id, content, item_type, topic_hint=note)
        if iid:
            imported += 1
        # 避免并发过快
        import asyncio
        await asyncio.sleep(0.1)

    # 迁移完把文件重命名，避免重复迁
    backup = PENDING_JSON.with_suffix(".json.migrated")
    PENDING_JSON.rename(backup)
    print(f"[Workspace] ✅ 迁移 {imported} 条素材，原文件 → {backup.name}", flush=True)
    return imported