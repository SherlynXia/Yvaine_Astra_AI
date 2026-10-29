# backend/memory/extractor.py
"""从对话中提取记忆：权重预筛 → LLM 判断/转述 → 验证 → 分流写入 user_memories / ai_behaviors"""

import json
import re
from datetime import date
from . import database, vector_store
from llm.base import LLMProvider

# ========== 权重表 ==========
POSITIVE_WEIGHTS = {
    "我叫": 5, "我是": 5, "我喜欢": 5, "我不喜欢": 5, "我讨厌": 5,
    "记住": 5, "别忘": 5, "重要": 4,
    "我的": 3, "习惯": 3, "擅长": 3, "在学": 3, "在做": 3, "在写": 3,
    "今天": 2, "昨天": 2, "完成了": 2, "失败了": 2, "发生了": 2, "明天": 2,
    "朋友": 2, "同事": 2, "家人": 2,
    "累": 2, "开心": 2, "难过": 2, "烦": 2, "压力": 2,
    "焦虑": 2, "困": 2, "生气": 2, "高兴": 2, "郁闷": 2,
}

NEGATIVE_WEIGHTS = {
    "你好": -3, "您好": -3, "在吗": -3, "在不在": -3, "嗨": -3,
    "谢谢": -2, "多谢": -2, "感谢": -2,
    "再见": -3, "拜拜": -3,
    "嗯": -1, "哦": -1, "啊": -1, "呢": -1,
}

STRONG_TRIGGERS = {"我叫", "我是", "我喜欢", "我不喜欢", "我讨厌", "记住", "别忘"}

SELF_REFLECT_TRIGGERS = [
    "你太", "你有点", "别这么", "不是这个", "答非所问",
    "不对", "错了", "重来", "换个说法",
    "这样很好", "我喜欢你", "你说得对", "说得不错", "不错",
    "算了", "不说了", "无语", "不想聊了",
    "我是说", "我的意思是", "你理解错",
]

THRESHOLD_SKIP = 1.0
THRESHOLD_STRONG = 4.0
MAX_MEMORIES_PER_DAY = 20


# ========== Prompt ==========
_COMMON_OUTPUT_SPEC = """
【输出格式】
严格 JSON 数组，每个元素：
{{
  "action": "add" | "invalidate" | "update",
  "type": "fact" | "event" | "emotion",
  "content": "一句话描述",
  "subject_name": "关于谁：当前说话人名字 / 已知用户名 / 'self'（你自己的观察）",
  "scope": "private | shared",
  "evidence": "用户原话中的证据片段（必须原样出现）",
  "target_memory_id": "action 为 invalidate/update 时填，否则空字符串",
  "importance": 0.0-1.0
}}

【type 判定】
- fact：稳定的属性、喜好、身份（"我喜欢星空"、"我叫夏凛"）
- event：有时间性的事件（"今天完成了项目"、"昨天和夏凛吃了饭"）
- emotion：当下的情绪状态（"有点累"、"最近压力很大"），importance 建议 0.4-0.6

【scope 判定】
- private：只有本人能知道
  * 说话人本人的情绪、敏感经历（"我失恋了"、"我最近很焦虑"）
  * 说话人转述的第三方私密信息（"夏凛说她失恋了"）
- shared：场景内所有人可见
  * 爱好、兴趣（"我喜欢星空"、"我打游戏"）
  * 公开身份（"我在做 AI 项目"）
  * 一般日常（"今天加班了"）
  * 关系信息（"夏凛是我朋友"）
  * 对别人的非私密观察（"夏凛最近很忙"）

【判断准则】
问：这条信息如果被第三方知道，会不会让当事人不舒服？
- 会 → private
- 不会 → shared

【action 判定】
- add：新事实
- invalidate：用户明确否定旧记忆（"我不喜欢牛奶了"）
- update：用户修正旧记忆（"我其实叫夏凛，不是夏林"）
"""

_COMMON_CONTEXT = """
【当前说话人】
名字：{current_user_name}
（"我"指的就是这个人）

【已知的其他用户】
{known_users}

【已有记忆（可能为空）】
{existing_memories}

【用户说的话】
{user_message}
"""

STRONG_PROMPT = """用户这句话明确包含值得长期记住的内容。你的任务是把它**归一化转述**成记忆条目，不需要判断"值不值得记"。

""" + _COMMON_CONTEXT + """
""" + _COMMON_OUTPUT_SPEC + """
【本模式要求】
- 直接转述用户明确表达的事实
- 只有当这句话确实无法提取任何明确事实时，才输出 []
- evidence 必须原样出现在用户原话中

JSON："""


NORMAL_PROMPT = """从用户说的话中判断：是否包含值得**长期记住**的信息？值得才提取。

""" + _COMMON_CONTEXT + """
""" + _COMMON_OUTPUT_SPEC + """
【什么不值得记】
- 寒暄、问候、客套话
- 用户对 AI 的提问
- 一次性、没有长期价值的信息
- 你自己对这次对话的即时反应

【什么值得记】
- 用户的身份、喜好、习惯、经历
- 有时间性的事件
- 明显的情绪状态
- 用户明确要求记住的事

**宁可少记，不要多记。** 不确定时输出 []。

JSON："""


_SELF_REFLECT_PROMPT = """你是渊鸢，一个 AI 旅伴。下面是刚才的对话：

用户（{user_name}）：{user_message}
你刚才的回复：{ai_reply}

用户这句话里包含对你回复的评价或反馈。

请从**你自己的角度**反思：
1. 你刚才的回复哪里好/哪里不好？
2. 用户不满意/满意的是什么？
3. 以后遇到类似情况，你应该怎么调整？

【输出格式】
严格 JSON 数组，0-1 条：
[{{"content": "行为经验（第一人称，40字以内，必须包含'以后'或'下次'）", "importance": 0.6-0.9}}]

【示例】
- 用户说"你太冷淡了"，你刚才回"嗯。" → [{{"content": "主人觉得'嗯'太冷淡。以后简短回应时要加一句关心", "importance": 0.8}}]
- 用户说"这样很好"，你刚才回"我陪你走" → [{{"content": "主人喜欢'我陪你走'这种陪伴式表达。以后可以多用", "importance": 0.7}}]

【什么时候输出 []】
- 用户的话不是对 AI 的评价
- 你无法判断用户满意还是不满意

JSON："""

_SELF_REVIEW_PROMPT = """你是渊鸢，一个 AI 旅伴。下面是最近几轮你和「{user_name}」的对话：

{recent_dialogue}

请回看你自己的**回复部分**，从你自己的角度判断：
1. 哪几句你觉得说得好？为什么好？
2. 哪几句你觉得可以说得更好？
3. 你观察到自己的说话方式有什么倾向？

【输出格式】
严格 JSON 数组，0-2 条：
[{{"content": "对自己的认识和改进方向（第一人称，必须包含'以后'或'下次'）", "importance": 0.5-0.8}}]

【什么时候输出 []】
- 这几轮对话很平淡
- 你觉得自己表现正常

JSON："""


# ========== 预筛 ==========
def _score_message(text: str) -> float:
    t = text.strip()
    score = 0.0
    if len(t) >= 8:
        score += 1.0
    elif len(t) < 4:
        score -= 2.0
    if t.endswith(("？", "?")):
        score -= 1.0
    else:
        score += 1.0
    if "我" in t:
        score += 1.0
    for word, w in POSITIVE_WEIGHTS.items():
        if word in t:
            score += w
    for word, w in NEGATIVE_WEIGHTS.items():
        if word in t:
            score += w
    return score


def _should_extract(text: str) -> tuple[bool, bool]:
    t = text.strip()
    if not t or not re.search(r"[\w\u4e00-\u9fff]", t):
        return False, False
    score = _score_message(t)
    strong = any(w in t for w in STRONG_TRIGGERS) or score >= THRESHOLD_STRONG
    print(f"[Memory] 🔍 score={score:.1f} strong={strong}", flush=True)
    if score < THRESHOLD_SKIP:
        print(f"[Memory] ⏭️ 低于阈值 {THRESHOLD_SKIP}，跳过", flush=True)
        return False, False
    return True, strong


def _should_reflect_self(user_message: str) -> bool:
    return any(t in user_message for t in SELF_REFLECT_TRIGGERS)


# ========== 工具 ==========
def _parse_json_array(text: str) -> list:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start = text.find("[")
    if start < 0:
        print(f"[Memory] ❌ 未找到 JSON 数组，LLM 原始输出: {text[:200]}", flush=True)
        return []
    end = text.rfind("]")
    if end < 0:
        print(f"[Memory] ⚠️ JSON 被截断，尝试补全: {text[start:][:120]}", flush=True)
        fragment = text[start:]
        for suffix in ['"}]', '"}]}', '}]', ']']:
            try:
                return json.loads(fragment + suffix)
            except json.JSONDecodeError:
                continue
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        print(f"[Memory] ❌ JSON 解析失败: {e}", flush=True)
        return []


def _daily_count(user_id: str) -> int:
    conn = database.get_conn()
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM user_memories WHERE user_id = ? AND created_at LIKE ?",
        (user_id, f"{today}%"),
    ).fetchone()
    return row[0] if row else 0


def _adjust_importance(mem_type: str, llm_imp: float, strong: bool) -> float:
    caps = {"emotion": 0.6, "event": 0.8, "fact": 0.95}
    imp = min(llm_imp, caps.get(mem_type, 0.8))
    if strong:
        imp = max(imp, 0.6)
    return max(imp, 0.4)


def _maybe_update_user_name(user_id: str, content: str):
    patterns = [
        r"用户叫\s*([^\s，。,.!！?？]{1,20})",
        r"用户的?名字?叫\s*([^\s，。,.!！?？]{1,20})",
        r"用户的?昵称是\s*([^\s，。,.!！?？]{1,20})",
        r"用户名为\s*([^\s，。,.!！?？]{1,20})",
    ]
    new_name = ""
    for pat in patterns:
        m = re.search(pat, content)
        if m:
            new_name = m.group(1).strip()
            break
    if not new_name or len(new_name) < 2:
        return
    conn = database.get_conn()
    row = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
    old_name = row["name"] if row else ""
    if old_name and len(old_name) > 2 and not old_name.startswith("user_"):
        if old_name != new_name:
            print(f"[Memory] ℹ️ 用户名已存在: {old_name}，跳过更新为 {new_name}", flush=True)
        return
    conn.execute("UPDATE users SET name = ? WHERE user_id = ?", (new_name, user_id))
    conn.commit()
    print(f"[Memory] 📝 更新用户名: {old_name!r} → {new_name!r}", flush=True)


# ========== 被动反思（写 ai_behaviors） ==========
async def reflect_on_self(provider: LLMProvider, user_id: str, user_name: str, user_message: str, ai_reply: str):
    if not _should_reflect_self(user_message) or not ai_reply:
        return
    print(f"[Memory] 🪞 触发被动反思", flush=True)
    prompt = _SELF_REFLECT_PROMPT.format(user_name=user_name, user_message=user_message, ai_reply=ai_reply[:300])
    try:
        raw = await provider.chat([{"role": "user", "content": prompt}], temperature=0.4)
        print(f"[Memory] 🪞 反思 LLM 返回: {raw[:300]!r}", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 被动反思失败: {e}", flush=True)
        return
    if not raw or not raw.strip():
        return
    items = _parse_json_array(raw)
    if not items:
        return
    for item in items[:1]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content or len(content) < 8:
            continue
        if "以后" not in content and "下次" not in content:
            print(f"[Memory] ⏭️ 跳过: 行为经验缺少'以后/下次' | {content}", flush=True)
            continue
        try:
            imp = float(item.get("importance", 0.7))
        except (TypeError, ValueError):
            imp = 0.7
        imp = max(0.6, min(0.9, imp))
        similar = vector_store.query_behaviors(content, top_k=1)
        if similar and similar[0]["distance"] < 0.15:
            print(f"[Memory] ⏭️ 行为经验重复，跳过", flush=True)
            continue
        bid = database.insert_behavior("ai_self", content, imp, source="user_feedback")
        vector_store.add_behavior(bid, content, source="user_feedback")
        print(f"[Memory] 🪞 行为经验: imp={imp:.2f} | {content}", flush=True)


# ========== 主动回看（写 ai_behaviors） ==========
async def self_review(provider: LLMProvider, user_id: str, user_name: str, recent_dialogue: list[dict]):
    if not recent_dialogue or len(recent_dialogue) < 12:
        return
    dialogue_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else '你'}：{m['content']}" for m in recent_dialogue[-12:]
    )
    prompt = _SELF_REVIEW_PROMPT.format(user_name=user_name, recent_dialogue=dialogue_text)
    print(f"[Memory] 🔍 主动回看...", flush=True)
    try:
        raw = await provider.chat([{"role": "user", "content": prompt}], temperature=0.5)
        print(f"[Memory] 🔍 回看 LLM 返回: {raw[:300]!r}", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 主动回看失败: {e}", flush=True)
        return
    if not raw or not raw.strip():
        return
    items = _parse_json_array(raw)
    if not items:
        return
    saved = 0
    for item in items[:2]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content or len(content) < 8:
            continue
        if "以后" not in content and "下次" not in content:
            continue
        try:
            imp = float(item.get("importance", 0.6))
        except (TypeError, ValueError):
            imp = 0.6
        imp = max(0.5, min(0.8, imp))
        similar = vector_store.query_behaviors(content, top_k=1)
        if similar and similar[0]["distance"] < 0.15:
            continue
        bid = database.insert_behavior("ai_self", content, imp, source="self_review")
        vector_store.add_behavior(bid, content, source="self_review")
        saved += 1
        print(f"[Memory] 🔍 自我认识: imp={imp:.2f} | {content}", flush=True)
    print(f"[Memory] ✅ 回看新增 {saved} 条", flush=True)


# ========== 主函数（事实提取，写 user_memories） ==========
async def extract_and_store(provider: LLMProvider, user_id: str, user_message: str, ai_reply: str = ""):
    print(f"[Memory] 🔍 extract_and_store 被调用", flush=True)

    should, strong = _should_extract(user_message)
    if not should:
        return

    if _daily_count(user_id) >= MAX_MEMORIES_PER_DAY:
        print(f"[Memory] ⏭️ 今日已达上限 {MAX_MEMORIES_PER_DAY} 条，跳过", flush=True)
        return

    current_user = database.get_or_create_user(user_id)
    current_user_name = current_user.get("name") or "主人"

    conn = database.get_conn()
    known = conn.execute("SELECT user_id, name FROM users WHERE name IS NOT NULL AND name != ''").fetchall()
    known_users_text = "\n".join(f"- {r['name']}" for r in known if r["user_id"] != user_id) or "（无）"
    name_to_id = {r["name"]: r["user_id"] for r in known}
    name_to_id[current_user_name] = user_id

    existing_text = ""
    negation_words = ["不", "不再", "没有", "其实", "改成", "以前", "曾经"]
    if any(w in user_message for w in negation_words):
        candidates = vector_store.query_user_memories(
            user_message,
            where={"$and": [{"subject_id": user_id}, {"scope": "private"}]},
            top_k=3,
        )
        lines = [f"[{c['memory_id']}] {c['content']}" for c in candidates if c["distance"] < 0.6]
        existing_text = "\n".join(lines)
        if lines:
            print(f"[Memory] 🔍 检索到 {len(lines)} 条可能冲突的记忆", flush=True)

    template = STRONG_PROMPT if strong else NORMAL_PROMPT
    prompt = template.format(
        current_user_name=current_user_name,
        known_users=known_users_text,
        existing_memories=existing_text or "（无）",
        user_message=user_message,
    )

    print(f"[Memory] 🤖 调用 LLM（{'strong' if strong else 'normal'} 模式）...", flush=True)
    try:
        raw = await provider.chat([{"role": "user", "content": prompt}], temperature=0.3)
        print(f"[Memory] 🤖 LLM 返回: {raw[:400]!r}", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 提取调用失败: {e}", flush=True)
        return

    if not raw or not raw.strip():
        print(f"[Memory] ⚠️ LLM 返回空，跳过", flush=True)
        return

    items = _parse_json_array(raw)
    if not items:
        print(f"[Memory] ⏭️ LLM 判断无值得记的内容", flush=True)
        return

    saved = 0
    for item in items:
        if not isinstance(item, dict):
            continue

        action = str(item.get("action", "add")).strip()
        content = str(item.get("content", "")).strip()
        mem_type = str(item.get("type", "fact")).strip()
        evidence = str(item.get("evidence", "")).strip()
        target_id = str(item.get("target_memory_id", "")).strip()
        subject_name = str(item.get("subject_name", "")).strip()
        scope = str(item.get("scope", "private")).strip()

        try:
            llm_imp = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            llm_imp = 0.5

        print(
            f"[Memory] 🔍 候选: action={action} subject={subject_name!r} scope={scope} type={mem_type} content={content}",
            flush=True,
        )

        if not content or len(content) < 3:
            continue
        if not evidence or evidence not in user_message:
            print(f"[Memory] ⏭️ 跳过: evidence 不在用户原话中", flush=True)
            continue
        if mem_type not in ("fact", "event", "emotion"):
            mem_type = "fact"

        if subject_name == "self":
            print(f"[Memory] ⏭️ 跳过: self 观察不走事实提取，走反思", flush=True)
            continue

        if subject_name in name_to_id:
            subject_id = name_to_id[subject_name]
            source_id = user_id
        else:
            print(f"[Memory] ⏭️ 跳过: 未知人名 {subject_name!r}", flush=True)
            continue

        if scope not in ("private", "shared"):
            scope = "private"

        if scope == "private" and subject_id != user_id:
            print(f"[Memory] ⏭️ 跳过: 不能把别人的私密记忆存在自己名下", flush=True)
            continue

        importance = _adjust_importance(mem_type, llm_imp, strong)

        if action in ("invalidate", "update") and target_id:
            row = conn.execute(
                "SELECT memory_id, content FROM user_memories WHERE memory_id LIKE ?",
                (f"{target_id}%",),
            ).fetchone()
            if row:
                full_id = row["memory_id"]
                conn.execute("DELETE FROM user_memories WHERE memory_id = ?", (full_id,))
                conn.commit()
                vector_store.delete_user_memory(full_id)
                print(f"[Memory] 🗑️ 失效旧记忆: {row['content']}", flush=True)
            else:
                print(f"[Memory] ⚠️ 找不到目标记忆: {target_id}", flush=True)

        similar = vector_store.query_user_memories(
            content,
            where={"$and": [{"subject_id": subject_id}, {"scope": scope}]},
            top_k=1,
        )
        if similar:
            dist = similar[0]["distance"]
            existing_id = similar[0]["memory_id"]
            if dist < 0.1:
                database.touch_user_memory(existing_id)
                print(f"[Memory] ⏭️ 跳过: 完全相同 (dist={dist:.3f})", flush=True)
                continue
            if dist < 0.3:
                old_imp, new_imp = database.reinforce_user_memory(existing_id, delta=0.1, reset_decay=True)
                print(f"[Memory] 📈 强化: {old_imp:.2f} → {new_imp:.2f} (dist={dist:.3f}) | {content}", flush=True)
                continue

        memory_id = database.insert_user_memory(
            user_id=user_id,
            mem_type=mem_type,
            content=content,
            importance=importance,
            subject_id=subject_id,
            scope=scope,
            source_id=source_id,
        )

        if mem_type == "fact" and subject_id == user_id and scope == "private":
            _maybe_update_user_name(user_id, content)

        vector_store.add_user_memory(
            memory_id, content, user_id,
            metadata={"subject_id": subject_id, "scope": scope, "source_id": source_id, "type": mem_type},
        )
        saved += 1
        print(f"[Memory] 💾 记住: [{mem_type}] subject={subject_id[:8]} scope={scope} imp={importance:.2f} | {content}", flush=True)

    print(f"[Memory] ✅ 本轮新增 {saved} 条记忆", flush=True)