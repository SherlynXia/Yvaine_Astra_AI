# backend/memory/extractor.py
"""从对话中提取记忆：权重预筛 → LLM 判断/转述 → 验证 → 分流写入 user_memories / ai_behaviors"""

import json
import re
from datetime import date
from . import database, vector_store, workspace, relationship
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
  "memory_layer": "user" | "workspace",
  "type": "fact" | "event" | "emotion",
  "content": "一句话描述",
  "subject_name": "关于谁：当前说话人名字 / 已知用户名 / 'self'（你自己的观察）",
  "scope": "private | shared",
  "evidence": "用户原话中的证据片段（必须原样出现）",
  "target_memory_id": "action 为 invalidate/update 时填，否则空字符串",
  "importance": 0.0-1.0,
  "expires_in_days": null,
  "item_type": "setting | character | plot | idea | draft",
  "topic_hint": "话题提示（15字以内）",
  "relation_info": null,
  "mentioned_relations": []

}}

【memory_layer 判定（最重要）】
- user：关于**人本身**的稳定信息
  * 强信号：我叫/我是/我喜欢/我讨厌/长期情绪（"我最近很焦虑"）/明确关系（"X 是我朋友"）
  * 跨话题仍然成立的事实
  * 用户明确要求长期记住的事
- workspace：当前创作/讨论/项目的**素材、设定、情节、角色**
  * "绘星的设定是…""这个角色叫…""我在构思…""这个情节要…"
  * 只对当前话题/项目有意义的临时想法、草稿
  * **拿不准时默认 workspace**（宁可进工作记忆，也不要污染长期记忆）
- 判断准则：这条信息**3 个月后**还成立吗？
  * 成立且关于人 → user
  * 只在这个项目/这段对话里成立 → workspace
  * 寒暄、提问 → 不输出

【type 判定】（memory_layer=user 时才有意义）
- fact：稳定的属性、喜好、身份、长期目标
- event：有时间性、跨话题仍成立的事件
- emotion：当下的情绪状态，importance 建议 0.4-0.6

【expires_in_days 判定】（仅 memory_layer=user 且 type=event）
- null：永不过期
- 具体天数：**不含缓冲**，填实际相对天数
  * "今天" → 1
  * "明天" / "明天上午" → 1
  * "后天" → 2
  * "这周末" → 7
  * "下周一" → 7
  * "下个月" → 30
- 准则：这件事**过了那个时间点**还有意义吗？没有 → 填天数
- 重要：不要预留缓冲。到点即过期，宁早勿晚。

【item_type 判定】（仅 memory_layer=workspace）
- setting：世界观、地理、规则、背景设定
- character：角色、人物、性格、关系
- plot：情节、剧情走向、事件发展
- idea：灵感、想法、概念、思路
- draft：草稿、初步方案、临时内容

【scope 判定】
- private：只有本人能知道（情绪、敏感经历、第三方私密信息）
- shared：场景内所有人可见（爱好、公开身份、关系、一般日常）

【action 判定】
- add：新内容
- invalidate：用户明确否定旧记忆（"我不喜欢牛奶了"）
- update：用户修正旧记忆（"我其实叫夏凛，不是夏林"）

【relation_info 判定】
- 仅当用户**明确说出**关系声明时填写，否则填 null（大多数情况）
- action 判定：
  * add：首次声明关系（"夏凛是我朋友"）
  * update：修正/改变已有关系（"夏凛现在是我女朋友了"、"夏凛不算朋友，是同事"）
  * invalidate：否定/解除关系（"夏凛不是我朋友了"、"我和夏凛闹掰了"）
- relation_type（invalidate 时填 "unknown"）：
  * friend / family / colleague / partner / rival
- confidence：
  * 用户明确声明 → 0.9
  * 用户转述 → 0.7
  * 模糊不清 → 0.4（低于 0.5 不写入）
- evidence 必须原样出现在用户原话中
- closeness（0.0-1.0，用户表达的亲密程度）：
  * 0.8-1.0：生死之交、发小、家人级别（"从小一起长大"、"最好的朋友"）
  * 0.5-0.8：好朋友、经常来往（"我朋友"、"经常一起玩"）
  * 0.2-0.5：普通朋友、同事、同学（"算是朋友"、"同事"）
  * 0.0-0.2：泛泛之交、刚认识（"认识"、"见过几面"）
  * 用户没说关系强度时填 0.3（默认普通朋友）
- 示例：
  用户「夏凛是我朋友」→
  "relation_info": {{"action":"add","target_name":"夏凛","relation_type":"friend","confidence":0.9,"closeness":0.4,"evidence":"夏凛是我朋友"}}
  用户「夏凛现在是我女朋友了」→
  "relation_info": {{"action":"update","target_name":"夏凛","relation_type":"partner","confidence":0.9,"evidence":"夏凛现在是我女朋友了"}}
  用户「夏凛不是我朋友了」→
  "relation_info": {{"action":"invalidate","target_name":"夏凛","relation_type":"unknown","confidence":0.9,"evidence":"夏凛不是我朋友了"}}
  用户「今天天气不错」→
  "relation_info": null

【mentioned_relations 判定】
- 仅当用户消息提到**已知的其他用户**，且对该人有情感倾向时填写
- 不是提到就填，必须是"有情感表达"（正面/负面），中性陈述不填
- 每条格式：{{"name":"夏凛","sentiment":0.8}}
- sentiment：-1.0 到 1.0
  * 正面（"夏凛很好"、"夏凛带我去玩"）→ 0.5-1.0
  * 负面（"夏凛好烦"、"夏凛老跟我抬杠"）→ -1.0 到 -0.5
  * 轻微（"夏凛有点奇怪"）→ -0.4 到 -0.2
- 没有提到人，或情感中性 → 填 []
- 示例：
  用户「夏凛今天带我去吃好吃的」→ "mentioned_relations": [{{"name":"夏凛","sentiment":0.8}}]
  用户「夏凛最近老跟我抬杠」→ "mentioned_relations": [{{"name":"夏凛","sentiment":-0.6}}]
  用户「夏凛今天在会上发言了」→ "mentioned_relations": []
  用户「今天天气不错」→ "mentioned_relations": []  

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
- **memory_layer 强制为 "user"**（用户明确要求记住的内容，一律进长期记忆，不走 workspace）
- 若用户要求记住的是**当前话题素材/设定细节**（不是关于人本身的稳定属性），
  content 必须以「（话题素材）」开头，便于后续识别
  例：用户说"记住，绘星的设定是有行星" →
      {{"memory_layer":"user","type":"fact","content":"（话题素材）绘星的设定是有行星","evidence":"绘星的设定是有行星",...}}
- 只有当这句话确实无法提取任何明确事实时，才输出 []
- evidence 必须原样出现在用户原话中

JSON："""


NORMAL_PROMPT = """从用户说的话中判断：是否包含值得**长期记住**的信息？值得才提取。

""" + _COMMON_CONTEXT + """
""" + _COMMON_OUTPUT_SPEC + """
【什么不输出（输出 []）】
- 寒暄、问候、客套话
- 用户对 AI 的提问
- 一次性、没有长期价值的信息
- 你自己对这次对话的即时反应

【什么进 user_memories（memory_layer=user）】
- 用户本人**稳定的**身份、喜好、习惯、长期目标、经历
- 跨话题仍然成立的事实
- 有明显情绪价值的状态（"我最近很焦虑"）
- 用户**明确要求**记住的事

【什么进 workspace（memory_layer=workspace）】
- 用户当前正在创作、讨论、构思的**素材、设定、情节、角色**
  （"绘星的设定是…""这个角色叫…""我在构思一个…""这个情节要…"）
- 只对当前话题/项目有意义的临时想法、草稿、思路
- 判断：这条信息只在这个项目/这段对话里成立吗？是 → workspace

【判断准则】
- 3 个月后还成立，且关于人本身 → user
- 只在这个项目/这段对话里成立 → workspace
- **拿不准 → workspace**（宁可进工作记忆，也不要污染长期记忆）
- 寒暄、提问 → 不输出

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

_MERGE_PROMPT = """下面两条记忆说的是同一件事，请合并成一句。

旧：{old}
新：{new}

要求：
- 保留所有关键信息（时间、人物、细节、数字）
- 去掉重复和冗余表述
- 30 字以内
- 直接输出合并后的句子，不要解释、不要引号、不要前缀

合并结果："""


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

    # 先尝试完整解析
    end = text.rfind("]")
    if end >= 0:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as e:
            print(f"[Memory] ❌ 完整解析失败: {e}，尝试截断补全", flush=True)

    # 截断补全：从后往前找最后一个完整的 }，配 ]
    fragment = text[start:]
    last_brace = fragment.rfind("}")
    while last_brace > 0:
        candidate = fragment[:last_brace + 1] + "]"
        try:
            result = json.loads(candidate)
            print(f"[Memory] ⚠️ JSON 截断，保留前 {len(result)} 条", flush=True)
            return result
        except json.JSONDecodeError:
            last_brace = fragment.rfind("}", 0, last_brace)

    print(f"[Memory] ❌ JSON 无法补全，LLM 原始输出: {text[start:][:200]}", flush=True)
    return []

async def _llm_merge(provider: LLMProvider, old_content: str, new_content: str) -> str | None:
    """LLM 重写合并。失败返回 None，调用方降级为追加。"""
    try:
        raw = await provider.chat(
            [{"role": "user", "content": _MERGE_PROMPT.format(old=old_content, new=new_content)}],
            temperature=0.2,
        )
        merged = (raw or "").strip().strip('"').strip("「」").strip()
        if not merged or len(merged) < 5:
            return None
        return merged[:120]
    except Exception as e:
        print(f"[Memory] ⚠️ LLM 合并失败: {e}", flush=True)
        return None

def _daily_count(user_id: str) -> int:
    from datetime import timedelta
    conn = database.get_conn()
    today_start = date.today().isoformat()
    tomorrow_start = (date.today() + timedelta(days=1)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) FROM user_memories "
        "WHERE user_id = ? AND created_at >= ? AND created_at < ?",
        (user_id, today_start, tomorrow_start),
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
    saved_ws = 0
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
        memory_layer = str(item.get("memory_layer", "user")).strip()

        try:
            llm_imp = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            llm_imp = 0.5

        print(
            f"[Memory] 🔍 候选: layer={memory_layer} action={action} subject={subject_name!r} "
            f"scope={scope} type={mem_type} content={content}",
            flush=True,
        )

        if not content or len(content) < 3:
            continue
        if not evidence or evidence not in user_message:
            print(f"[Memory] ⏭️ 跳过: evidence 不在用户原话中", flush=True)
            continue

        # ===== 分流：workspace 走独立路径 =====
        if memory_layer not in ("user", "workspace"):
            memory_layer = "user"
        if strong:
            memory_layer = "user"   # strong 模式强制进长期记忆

        if memory_layer == "workspace":
            item_type = str(item.get("item_type", "setting")).strip()
            if item_type not in ("setting", "character", "plot", "idea", "draft"):
                item_type = "setting"
            topic_hint = str(item.get("topic_hint", "")).strip()
            try:
                iid = await workspace.record_item(
                    provider, user_id, content, item_type, topic_hint
                )
                if iid:
                    saved_ws += 1
            except Exception as e:
                print(f"[Memory] ⚠️ workspace 写入失败: {e}", flush=True)
            continue

        # 关系信息（独立于记忆写入，无论这条记忆最终是否入库都记录关系）
        relation_info = item.get("relation_info")
        if relation_info and isinstance(relation_info, dict):
            rel_evidence = str(relation_info.get("evidence", "")).strip()
            if not rel_evidence or rel_evidence not in user_message:
                print(f"[Memory] ⏭️ 关系证据不在原话中，跳过", flush=True)
            else:
                rel_action = str(relation_info.get("action", "add")).strip()
                try:
                    if rel_action == "invalidate":
                        target_name = str(relation_info.get("target_name", "")).strip()
                        conn2 = database.get_conn()
                        trow = conn2.execute(
                            "SELECT user_id FROM users WHERE name = ?", (target_name,)
                        ).fetchone()
                        if trow:
                            n = database.invalidate_user_user_relationship(
                                user_id, trow["user_id"]
                            )
                            print(
                                f"[Relation] 🗑️ 解除关系: {user_id[:8]} ✕ {target_name} ({n} 条)",
                                flush=True,
                            )
                        else:
                            print(f"[Relation] ⏭️ 解除失败，目标用户不存在: {target_name}", flush=True)
                    else:
                        # add / update：update 时强制覆盖类型
                        relation_info["_allow_overwrite"] = (rel_action == "update")
                        relationship.update_from_relation_info(user_id, relation_info)
                except Exception as e:
                    print(f"[Memory] ⚠️ 关系写入失败: {e}", flush=True)

        # AI 观察：用户对某人的情感倾向
        mentioned = item.get("mentioned_relations", [])
        if isinstance(mentioned, list):
            for m in mentioned:
                if not isinstance(m, dict):
                    continue
                name = str(m.get("name", "")).strip()
                try:
                    sentiment = float(m.get("sentiment", 0))
                except (TypeError, ValueError):
                    continue
                if not name or abs(sentiment) < 0.2:
                    continue
                trow = conn.execute(
                    "SELECT user_id FROM users WHERE name = ?", (name,)
                ).fetchone()
                if not trow:
                    continue
                target_uid = trow["user_id"]
                if target_uid == user_id:
                    continue
                try:
                    database.update_observed_sentiment(user_id, target_uid, sentiment)
                    print(
                        f"[Relation] 👀 观察: {user_id[:8]} 对 {name} "
                        f"sentiment={sentiment:+.2f}",
                        flush=True,
                    )
                except Exception as e:
                    print(f"[Memory] ⚠️ 观察记录失败: {e}", flush=True)

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
        # 解析过期时间
        expires_at = None
        raw_days = item.get("expires_in_days")
        if raw_days is not None:
            try:
                days = float(raw_days)
                if days > 0:
                    from datetime import datetime, timedelta
                    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
            except (TypeError, ValueError):
                pass
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

        # 检索候选：多取几条，按 type 过滤，避免 fact/event 互相误伤
        similar = vector_store.query_user_memories(
            content,
            where={"$and": [{"subject_id": subject_id}, {"scope": scope}]},
            top_k=3,
        )
        candidate = None
        for c in similar:
            if c["metadata"].get("type") == mem_type:
                candidate = c
                break

        if candidate:
            dist = candidate["distance"]
            existing_id = candidate["memory_id"]

            # 完全相同：只 touch
            if dist < 0.08:
                database.touch_user_memory(existing_id)
                print(f"[Memory] ⏭️ 跳过: 完全相同 (dist={dist:.3f})", flush=True)
                continue

            # 高度相似：LLM 重写合并 + 强化权重
            if dist < 0.15:
                old = database.get_user_memory(existing_id)
                if old and content not in old["content"]:
                    merged = await _llm_merge(provider, old["content"], content)
                    if merged and merged != old["content"]:
                        database.update_memory_content(existing_id, merged)
                        vector_store.update_user_memory(existing_id, merged)
                        print(
                            f"[Memory] 🔀 LLM 合并: {old['content'][:30]} + {content[:30]} → {merged[:50]}",
                            flush=True,
                        )
                    else:
                        # LLM 失败/无变化 → 降级追加，不丢新内容
                        fallback = old["content"] + "；" + content
                        database.update_memory_content(existing_id, fallback)
                        vector_store.update_user_memory(existing_id, fallback)
                        print(f"[Memory] 🔀 追加(降级): {fallback[:80]}", flush=True)

                if expires_at:
                    old_exp = old.get("expires_at") if old else None
                    if not old_exp or old_exp < expires_at:
                        conn.execute(
                            "UPDATE user_memories SET expires_at = ? WHERE memory_id = ?",
                            (expires_at, existing_id),
                        )
                        conn.commit()

                old_imp, new_imp = database.reinforce_user_memory(
                    existing_id, delta=0.1, reset_decay=True
                )
                print(
                    f"[Memory] 📈 强化: {old_imp:.2f} → {new_imp:.2f} (dist={dist:.3f})",
                    flush=True,
                )
                continue

            # dist >= 0.15：不合并，fall through 走 insert（新记忆正常落库）

        memory_id = database.insert_user_memory(
            user_id=user_id,
            mem_type=mem_type,
            content=content,
            importance=importance,
            subject_id=subject_id,
            scope=scope,
            source_id=source_id,
            expires_at=expires_at,
        )

        if mem_type == "fact" and subject_id == user_id and scope == "private":
            _maybe_update_user_name(user_id, content)

        # 用户写入私密记忆 → intimacy +1
        if scope == "private" and subject_id == user_id:
            try:
                relationship.bump_private_intimacy(user_id)
            except Exception as e:
                print(f"[Memory] ⚠️ intimacy 更新失败: {e}", flush=True)

        vector_store.add_user_memory(
            memory_id, content, user_id,
            metadata={"subject_id": subject_id, "scope": scope, "source_id": source_id, "type": mem_type},
        )
        saved += 1
        print(f"[Memory] 💾 记住: [{mem_type}] subject={subject_id[:8]} scope={scope} imp={importance:.2f} | {content}", flush=True)

    print(
        f"[Memory] ✅ 本轮新增: user_memories {saved} 条 / workspace {saved_ws} 条",
        flush=True,
    )