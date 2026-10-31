# backend/memory/relationship.py
"""关系网：AI ↔ 用户（三维）+ 用户 ↔ 用户（关系图）

注意：feedback 表（👍/👎）是训练数据，和本模块的 trust 无关。
trust 只来自对话内容中的口头表扬/批评。
"""

import re
from . import database

# ========== 权重 ==========
FAMILIARITY_PER_TURN = 1.0
INTIMACY_EMOTION_BONUS = 2.0
INTIMACY_PRIVATE_BONUS = 1.0
TRUST_VERBAL_PRAISE = 1.0
TRUST_VERBAL_CRITICISM = -1.0

# 分级阈值
STAGE_THRESHOLDS = [
    (80, "intimate"),
    (60, "close"),
    (35, "friend"),
    (15, "acquaintance"),
    (0, "stranger"),
]

# 对话中的表扬词（trust +1，positive_count +1）
# 和 extractor.SELF_REFLECT_TRIGGERS 有重叠，但用途不同：
#   SELF_REFLECT_TRIGGERS → 触发 AI 自我反思（写 ai_behaviors）
#   _PRAISE_WORDS         → 触发关系网 trust 增长（写 ai_user_relationships）
_PRAISE_WORDS = [
    "你说得对", "说得不错", "这样很好", "我喜欢你", "不错",
    "谢谢", "感谢", "辛苦了",
]

# 对话中的批评词（trust -1，negative_count +1）
_CRITICISM_WORDS = [
    "你太", "你有点", "别这么", "不是这个", "答非所问",
    "不对", "错了", "你理解错", "无语",
]

# 情绪词（intimacy +2）
_EMOTION_WORDS = [
    "开心", "高兴", "难过", "累", "烦", "压力",
    "焦虑", "困", "生气", "郁闷", "失落", "兴奋",
]

# 关系关键词 → 类型
RELATION_KEYWORDS = {
    "好朋友": "friend", "朋友": "friend", "好友": "friend",
    "家人": "family", "妈妈": "family", "爸爸": "family",
    "父母": "family", "兄弟": "family", "姐妹": "family",
    "同事": "colleague", "同学": "colleague", "老板": "colleague", "上司": "colleague",
    "男朋友": "partner", "女朋友": "partner", "恋人": "partner",
    "对象": "partner", "老公": "partner", "老婆": "partner",
    "对手": "rival", "敌人": "rival",
}


def _now() -> str:
    return database._now()


def _calc_stage(intimacy: float) -> str:
    for threshold, stage in STAGE_THRESHOLDS:
        if intimacy >= threshold:
            return stage
    return "stranger"


# ========== AI ↔ 用户 ==========

def update_after_turn(user_id: str, user_message: str, ai_reply: str = "") -> None:
    """每轮对话结束后更新三维。trust 只来自对话内容，和 feedback 无关。"""
    rel = database.get_or_create_ai_user_relationship(user_id)

    familiarity = rel["familiarity"] + FAMILIARITY_PER_TURN
    trust = rel["trust"]
    intimacy = rel["intimacy"]
    pos = rel["positive_count"]
    neg = rel["negative_count"]

    if any(w in user_message for w in _EMOTION_WORDS):
        intimacy += INTIMACY_EMOTION_BONUS

    if any(w in user_message for w in _PRAISE_WORDS):
        trust += TRUST_VERBAL_PRAISE
        pos += 1
    elif any(w in user_message for w in _CRITICISM_WORDS):
        trust += TRUST_VERBAL_CRITICISM
        neg += 1

    database.update_ai_user_relationship(
        user_id,
        familiarity=min(1000.0, familiarity),
        trust=max(-50.0, min(100.0, trust)),
        intimacy=min(100.0, intimacy),
        stage=_calc_stage(intimacy),
        interaction_count=rel["interaction_count"] + 1,
        positive_count=pos,
        negative_count=neg,
        last_interaction=_now(),
    )


def bump_private_intimacy(user_id: str) -> None:
    """用户写入 private 记忆时调用，intimacy +1"""
    rel = database.get_ai_user_relationship(user_id)
    if not rel:
        return
    intimacy = min(100.0, rel["intimacy"] + INTIMACY_PRIVATE_BONUS)
    database.update_ai_user_relationship(
        user_id, intimacy=intimacy, stage=_calc_stage(intimacy),
    )


def get_intimacy(user_id: str) -> float:
    rel = database.get_ai_user_relationship(user_id)
    return rel["intimacy"] if rel else 0.0


def get_stage(user_id: str) -> str:
    rel = database.get_ai_user_relationship(user_id)
    return rel["stage"] if rel else "stranger"

# ========== 融合逻辑 ==========

def _fuse_relation(uid1: str, uid2: str) -> dict | None:
    """从 relation_claims + observed 融合出最终关系。

    融合规则：
    - 双方声明 + 类型一致：closeness = 双方声明均值 × 0.9
    - 单方声明：closeness = 声明值 × (0.4 + 0.5×min(1, mentions/10)) + observed×0.05
    - 只有观察：mentions < 5 → 0；否则 max(0, observed) × 0.3
    - 双方声明但类型冲突：降级为 acquaintance，closeness 按单方声明处理
    """
    a, b = database._normalize_pair(uid1, uid2)

    a_claim = database.get_relation_claim(a, b)
    b_claim = database.get_relation_claim(b, a)
    observed, mentions = database.get_observed(a, b)

    # 类型判定
    type_conflict = False
    if a_claim and b_claim:
        if a_claim["relation_type"] == b_claim["relation_type"]:
            relation_type = a_claim["relation_type"]
            is_mutual = 1
        else:
            relation_type = "acquaintance"
            is_mutual = 0
            type_conflict = True
    elif a_claim or b_claim:
        relation_type = (a_claim or b_claim)["relation_type"]
        is_mutual = 0
    else:
        relation_type = "unknown"
        is_mutual = 0

    # closeness 计算
    if a_claim and b_claim and not type_conflict:
        # 双方确认
        avg = (a_claim["stated_closeness"] + b_claim["stated_closeness"]) / 2
        closeness = avg * 0.9
    elif a_claim or b_claim:
        # 单方声明（包括双方声明但类型冲突的情况，取较高的作为声明值）
        if type_conflict:
            stated = max(a_claim["stated_closeness"], b_claim["stated_closeness"])
        else:
            stated = (a_claim or b_claim)["stated_closeness"]
        trust_factor = 0.4 + 0.5 * min(1.0, mentions / 10)
        closeness = stated * trust_factor + max(0.0, observed) * 0.05
    else:
        # 只有观察
        if mentions < 5:
            closeness = 0.0
        else:
            closeness = max(0.0, observed) * 0.3

    closeness = max(0.0, min(1.0, closeness))

    confidence = max(
        a_claim["confidence"] if a_claim else 0.0,
        b_claim["confidence"] if b_claim else 0.0,
    )

    return {
        "relation_type": relation_type,
        "closeness": closeness,
        "is_mutual": is_mutual,
        "confidence": confidence,
    }

# ========== 用户 ↔ 用户 ==========

def update_from_relation_info(user_id: str, relation_info: dict | None) -> None:
    """从 extractor 的 relation_info 写入单方声明 + 融合。"""
    if not relation_info or not isinstance(relation_info, dict):
        return
    target = str(relation_info.get("target_name", "")).strip()
    rtype = str(relation_info.get("relation_type", "")).strip()
    try:
        conf = float(relation_info.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    try:
        closeness = float(relation_info.get("closeness", 0.3))
    except (TypeError, ValueError):
        closeness = 0.3
    evidence = str(relation_info.get("evidence", ""))

    if not target or not rtype or conf < 0.5:
        return

    conn = database.get_conn()
    row = conn.execute("SELECT user_id FROM users WHERE name = ?", (target,)).fetchone()
    if not row:
        print(f"[Relation] ⏭️ 目标用户不存在: {target}", flush=True)
        return
    target_id = row["user_id"]
    if target_id == user_id:
        return

    # 1. 写单方声明
    database.upsert_relation_claim(
        claimant_id=user_id,
        target_id=target_id,
        relation_type=rtype,
        stated_closeness=closeness,
        confidence=conf,
        evidence=evidence,
        source="user_stated",
    )

    # 2. 融合
    fused = _fuse_relation(user_id, target_id)
    if not fused:
        return

    # 3. 更新最终表
    database.upsert_user_user_relationship(
        user_id, target_id,
        relation_type=fused["relation_type"],
        confidence=fused["confidence"],
        closeness=fused["closeness"],
        is_mutual=fused["is_mutual"],
        evidence=evidence,
        allow_overwrite=True,
    )

    print(
        f"[Relation] 🔗 {user_id[:8]} → {target} "
        f"(type={fused['relation_type']}, closeness={fused['closeness']:.2f}, "
        f"mutual={fused['is_mutual']})",
        flush=True,
    )


def try_auto_detect_relation(user_id: str, user_message: str) -> None:
    """兜底：正则识别 'X 是我 Y'。"""
    for kw, rtype in RELATION_KEYWORDS.items():
        pattern = r"([^\s，。,.!！?？]{1,20})(?:是|算是)(?:我的|[^，。,.!！?？]{0,10}的)?(" + kw + ")"
        m = re.search(pattern, user_message)
        if m:
            target_name = m.group(1).strip()
            if target_name and target_name != "我":
                update_from_relation_info(user_id, {
                    "target_name": target_name,
                    "relation_type": rtype,
                    "confidence": 0.9,
                    "evidence": m.group(0),
                })
            return


# ========== 注入 ==========

_TONE_MAP = {
    "stranger": "礼貌、克制，不越界，不主动提及他的过去",
    "acquaintance": "友好但保持距离，可引用共享事实，不提私密",
    "friend": "轻松自然，可以调侃、关心情绪",
    "close": "可以主动聊过去的事，用稍亲昵的语气",
    "intimate": "可以提及私密情绪，用亲昵称呼",
}


def get_relationship_block(user_id: str, user_name: str) -> str:
    rel = database.get_ai_user_relationship(user_id)
    if not rel:
        return ""

    parts = [f"【你和「{user_name}」的关系】"]
    parts.append(
        f"- 阶段：{rel['stage']}（亲密度 {rel['intimacy']:.0f}/100，"
        f"信任 {rel['trust']:.0f}）"
    )
    parts.append(
        f"- 互动 {rel['interaction_count']} 次，"
        f"口头表扬 {rel['positive_count']} 次，批评 {rel['negative_count']} 次"
    )
    parts.append(f"- 建议语气：{_TONE_MAP.get(rel['stage'], '自然')}")

    relations = database.list_user_relations(user_id, min_confidence=0.5)
    if relations:
        conn = database.get_conn()
        lines = []
        for r in relations:
            other = r["user_b"] if r["user_a"] == user_id else r["user_a"]
            row = conn.execute("SELECT name FROM users WHERE user_id = ?", (other,)).fetchone()
            other_name = row["name"] if row else other[:8]
            mutual = "（双方确认）" if r["is_mutual"] else ""
            lines.append(f"  - {other_name}：{r['relation_type']}{mutual}")
        if lines:
            parts.append("- 他认识的人：\n" + "\n".join(lines))

    return "\n".join(parts)

# ========== 隐私梯度 ==========

# 自己的记忆门槛（AI ↔ 用户 intimacy）
_VISIBILITY_THRESHOLDS = {
    ("fact", "private"):    {"own": 15, "other": None},
    ("fact", "shared"):     {"own": 0,  "other": 0},
    ("event", "private"):   {"own": 20, "other": None},
    ("event", "shared"):    {"own": 0,  "other": 0},
    ("emotion", "private"): {"own": 30, "other": None},
    ("emotion", "shared"):  {"own": 10, "other": 0},
}

# 别人的 shared 记忆需要 A-B 关系 closeness 达到的门槛
_OTHER_CLOSENESS_MIN = {
    "fact":    0.25,
    "event":   0.50,
    "emotion": 0.70,
}

# AI 对关系的置信度门槛（低于此完全不可见）
_OTHER_RELATION_MIN_CONF = 0.5


def check_memory_visibility(
    memory: dict,
    current_user_id: str,
    current_intimacy: float,
) -> tuple[bool, str]:
    """检查一条记忆对当前用户是否可见。"""
    mem_type = memory.get("type", "fact")
    scope = memory.get("scope", "private")
    subject_id = memory.get("subject_id", "")

    threshold = _VISIBILITY_THRESHOLDS.get(
        (mem_type, scope), {"own": 999, "other": None}
    )

    # 自己的记忆
    if subject_id == current_user_id:
        min_imp = threshold["own"]
        if min_imp is not None and current_intimacy >= min_imp:
            return True, "[你]"
        return False, ""

    # 别人的 private：永不
    if scope == "private":
        return False, ""

    # 别人的 shared：三道门槛
    rel = database.get_user_user_relationship(current_user_id, subject_id)
    if not rel or rel["confidence"] < _OTHER_RELATION_MIN_CONF:
        return False, ""

    min_close = _OTHER_CLOSENESS_MIN.get(mem_type, 0.5)
    if rel["closeness"] < min_close:
        return False, ""

    min_imp = threshold["other"]
    if min_imp is not None and current_intimacy < min_imp:
        return False, ""

    conn = database.get_conn()
    row = conn.execute("SELECT name FROM users WHERE user_id = ?", (subject_id,)).fetchone()
    name = row["name"] if row else "某人"
    return True, f"[{name}·公开]"