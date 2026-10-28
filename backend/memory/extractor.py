# backend/memory/extractor.py
"""从对话中提取记忆：权重预筛 → LLM 判断/转述 → 验证 → 写入"""

import json
import re
from datetime import date
from . import database, vector_store
from llm.base import LLMProvider

# ========== 权重表 ==========
POSITIVE_WEIGHTS = {
    # 强触发（标记 strong）
    "我叫": 5, "我是": 5, "我喜欢": 5, "我不喜欢": 5, "我讨厌": 5,
    "记住": 5, "别忘": 5, "重要": 4,
    # 属性
    "我的": 3, "习惯": 3, "擅长": 3, "在学": 3, "在做": 3, "在写": 3,
    # 事件
    "今天": 2, "昨天": 2, "完成了": 2, "失败了": 2, "发生了": 2, "明天": 2,
    # 关系
    "朋友": 2, "同事": 2, "家人": 2,
    # 情绪
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

THRESHOLD_SKIP = 1.0
THRESHOLD_STRONG = 4.0
MAX_MEMORIES_PER_DAY = 20


# ========== Prompt 公共部分 ==========
_COMMON_OUTPUT_SPEC = """
【输出格式】
严格 JSON 数组，每个元素：
{{
  "action": "add" | "invalidate" | "update",
  "type": "fact" | "event" | "emotion",
  "content": "一句话描述",
  "subject_name": "关于谁：当前说话人名字 / 已知用户名 / 'self'（你自己的观察）",
  "scope": "private | shared | ai_self",
  "evidence": "用户原话中的证据片段（必须原样出现）",
  "target_memory_id": "action 为 invalidate/update 时填，否则空字符串",
  "importance": 0.0-1.0
}}

【type 判定】
- fact：稳定的属性、喜好、身份（"我喜欢星空"、"我叫夏凛"）
- event：有时间性的事件（"今天完成了项目"、"昨天和夏凛吃了饭"）
- emotion：当下的情绪状态（"有点累"、"最近压力很大"），importance 建议 0.4-0.6

【scope 判定】
- private：某人本人的私密信息（喜好、经历、情绪、秘密），只有本人能知道
- shared：涉及多人、公共事件、关系信息，所有人可见
- ai_self：你自己的观察和感受

【关键区分】
- "夏凛说她失恋了" → subject_name=夏凛, scope=private（这是夏凛的私密信息）
- "夏凛最近很忙" → subject_name=夏凛, scope=shared（这是观察，不是私密）

【action 判定】
- add：新事实，与已有记忆不冲突
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

# ========== 两种 Prompt ==========
STRONG_PROMPT = """用户这句话明确包含值得长期记住的内容。你的任务是把它**归一化转述**成记忆条目，不需要判断"值不值得记"。

""" + _COMMON_CONTEXT + """
""" + _COMMON_OUTPUT_SPEC + """
【本模式要求】
- 直接转述用户明确表达的事实，不要省略
- 只有当这句话确实无法提取任何关于用户/他人的明确事实时，才输出 []
- evidence 必须原样出现在用户原话中

JSON："""


NORMAL_PROMPT = """从用户说的话中判断：是否包含值得**长期记住**的信息？值得才提取。

""" + _COMMON_CONTEXT + """
""" + _COMMON_OUTPUT_SPEC + """
【什么不值得记】
- 寒暄、问候、客套话（"你好"、"在吗"、"谢谢"）
- 用户对 AI 的提问（"你能做什么"、"今天天气怎么样"）
- 一次性的、没有长期价值的信息（"我现在打开了一个网页"）
- 用户已经说过且没变化的信息
- 你自己（渊鸢）对这次对话的即时反应

【什么值得记】
- 用户的身份、喜好、习惯、经历
- 有时间性的事件
- 明显的情绪状态
- 用户明确要求记住的事

**宁可少记，不要多记。** 不确定时输出 []。

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
    """返回 (是否调 LLM, 是否 strong 模式)"""
    t = text.strip()

    if not t or not re.search(r"[\w\u4e00-\u9fff]", t):
        return False, False

    score = _score_message(t)
    strong = (
        any(w in t for w in STRONG_TRIGGERS)
        or score >= THRESHOLD_STRONG
    )

    print(f"[Memory] 🔍 score={score:.1f} strong={strong}", flush=True)

    if score < THRESHOLD_SKIP:
        print(f"[Memory] ⏭️ 低于阈值 {THRESHOLD_SKIP}，跳过", flush=True)
        return False, False

    return True, strong


# ========== 工具 ==========
def _parse_json_array(text: str) -> list:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        print(f"[Memory] ❌ 未找到 JSON 数组，LLM 原始输出: {text[:200]}", flush=True)
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        print(f"[Memory] ❌ JSON 解析失败: {e}，原文: {text[start:end+1][:200]}", flush=True)
        return []


def _daily_count(user_id: str) -> int:
    conn = database.get_conn()
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE user_id = ? AND created_at LIKE ?",
        (user_id, f"{today}%"),
    ).fetchone()
    return row[0] if row else 0


def _adjust_importance(mem_type: str, llm_imp: float, strong: bool) -> float:
    caps = {"emotion": 0.6, "event": 0.8, "fact": 0.95}
    imp = min(llm_imp, caps.get(mem_type, 0.8))
    if strong:
        imp = max(imp, 0.6)
    return max(imp, 0.4)

def _maybe_update_user_name(user_id: str, content: str, current_name: str):
    """
    从记忆内容里检测"用户叫X"，更新 users.name。
    只在当前用户名是 UUID 前缀或"主人"时才覆盖。
    """
    # 匹配"用户叫X"、"用户的昵称是X"、"用户名字叫X"
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

    if not new_name:
        return

    # 只在新名字不像 UUID 前缀时才更新
    if len(new_name) < 2:
        return

    conn = database.get_conn()
    row = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
    old_name = row["name"] if row else ""

    # 旧名字已经是真名（非 UUID 前缀、非空），不覆盖
    if old_name and len(old_name) > 2 and not old_name.startswith("user_"):
        if old_name != new_name:
            print(f"[Memory] ℹ️ 用户名已存在: {old_name}，跳过更新为 {new_name}", flush=True)
        return

    conn.execute("UPDATE users SET name = ? WHERE user_id = ?", (new_name, user_id))
    conn.commit()
    print(f"[Memory] 📝 更新用户名: {old_name!r} → {new_name!r}", flush=True)

# ========== 主函数 ==========
async def extract_and_store(
    provider: LLMProvider,
    user_id: str,
    user_message: str,
    ai_reply: str = "",
):
    print(f"[Memory] 🔍 extract_and_store 被调用", flush=True)

    # 1. 预筛
    should, strong = _should_extract(user_message)
    if not should:
        return

    # 2. 每日预算
    if _daily_count(user_id) >= MAX_MEMORIES_PER_DAY:
        print(f"[Memory] ⏭️ 今日已达上限 {MAX_MEMORIES_PER_DAY} 条，跳过", flush=True)
        return

    # 3. 上下文
    current_user = database.get_or_create_user(user_id)
    current_user_name = current_user.get("name") or "主人"

    conn = database.get_conn()
    known = conn.execute(
        "SELECT user_id, name FROM users WHERE name IS NOT NULL AND name != ''"
    ).fetchall()
    known_users_text = "\n".join(
        f"- {r['name']}" for r in known if r["user_id"] != user_id
    ) or "（无）"
    name_to_id = {r["name"]: r["user_id"] for r in known}
    name_to_id[current_user_name] = user_id

    # 4. 冲突检索（含否定/修正词时）
    existing_text = ""
    negation_words = ["不", "不再", "没有", "其实", "改成", "以前", "曾经"]
    if any(w in user_message for w in negation_words):
        candidates = vector_store.query_vectors(
            user_message,
            where={"$and": [{"subject_id": user_id}, {"scope": "private"}]},
            top_k=3,
        )
        lines = [
            f"[{c['memory_id']}] {c['content']}"
            for c in candidates if c["distance"] < 0.6
        ]
        existing_text = "\n".join(lines)
        if lines:
            print(f"[Memory] 🔍 检索到 {len(lines)} 条可能冲突的记忆", flush=True)

    # 5. 选 Prompt
    template = STRONG_PROMPT if strong else NORMAL_PROMPT
    prompt = template.format(
        current_user_name=current_user_name,
        known_users=known_users_text,
        existing_memories=existing_text or "（无）",
        user_message=user_message,
    )

    print(f"[Memory] 🤖 调用 LLM（{'strong' if strong else 'normal'} 模式）...", flush=True)
    try:
        raw = await provider.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        print(f"[Memory] 🤖 LLM 返回: {raw[:400]!r}", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 提取调用失败: {e}", flush=True)
        return

    items = _parse_json_array(raw)
    if not items:
        print(f"[Memory] ⏭️ LLM 判断无值得记的内容", flush=True)
        return

    # 6. 逐条验证写入
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
            f"[Memory] 🔍 候选: action={action} subject={subject_name!r} "
            f"scope={scope} type={mem_type} content={content}",
            flush=True,
        )

        if not content or len(content) < 3:
            continue
        if not evidence or evidence not in user_message:
            print(f"[Memory] ⏭️ 跳过: evidence 不在用户原话中", flush=True)
            continue
        if mem_type not in ("fact", "event", "emotion", "reflection"):
            mem_type = "fact"

        # subject 映射
        if subject_name == "self":
            subject_id = "ai_self"
            source_id = "ai_self"
        elif subject_name in name_to_id:
            subject_id = name_to_id[subject_name]
            source_id = user_id
        else:
            print(f"[Memory] ⏭️ 跳过: 未知人名 {subject_name!r}，等你确认身份后再记", flush=True)
            continue

        if scope not in ("private", "shared", "ai_self"):
            scope = "private"

        # 安全：不能把别人的 private 存在自己名下
        if scope == "private" and subject_id != user_id:
            print(f"[Memory] ⏭️ 跳过: 不能把别人的私密记忆存在自己名下", flush=True)
            continue

        # importance 修正
        importance = _adjust_importance(mem_type, llm_imp, strong)

        # invalidate / update
        if action in ("invalidate", "update") and target_id:
            row = conn.execute(
                "SELECT memory_id, content FROM memories WHERE memory_id LIKE ?",
                (f"{target_id}%",),
            ).fetchone()
            if row:
                full_id, old_content = row["memory_id"], row["content"]
                conn.execute(
                    "UPDATE memories SET importance = 0.1, type = 'invalidated' WHERE memory_id = ?",
                    (full_id,),
                )
                conn.commit()
                vector_store.delete_vector(full_id)
                print(f"[Memory] 🗑️ 失效旧记忆: {old_content}", flush=True)
            else:
                print(f"[Memory] ⚠️ 找不到目标记忆: {target_id}", flush=True)

        # 去重
        similar = vector_store.query_vectors(
            content,
            where={"$and": [{"subject_id": subject_id}, {"scope": scope}]},
            top_k=1,
        )
        if similar and similar[0]["distance"] < 0.1:
            print(f"[Memory] ⏭️ 跳过: 重复", flush=True)
            continue

        # 写入
        memory_id = database.insert_memory(
            user_id=user_id,
            mem_type=mem_type,
            content=content,
            importance=importance,
            subject_id=subject_id,
            scope=scope,
            source_id=source_id,
        )

        # 🔥 检测"用户叫X"，同步更新 users.name
        if (
            mem_type == "fact"
            and subject_id == user_id
            and scope == "private"
        ):
            _maybe_update_user_name(user_id, content, current_user_name)
        vector_store.add_vector(
            memory_id, content, user_id,
            metadata={
                "subject_id": subject_id,
                "scope": scope,
                "source_id": source_id,
            },
        )
        saved += 1
        subj_display = "ai_self" if subject_id == "ai_self" else subject_id[:8]
        print(
            f"[Memory] 💾 记住: [{mem_type}] subject={subj_display} "
            f"scope={scope} imp={importance:.2f} | {content}",
            flush=True,
        )

    print(f"[Memory] ✅ 本轮新增 {saved} 条记忆", flush=True)