# backend/feedback/entropy.py
"""对话价值熵计算与筛网：每条对话都打分，只有过筛的才进候选池。"""

import math
import re
from collections import Counter

# 低信息量标记：命中且消息很短 → 直接丢弃
LOW_INFO_MARKERS = {
    "你好", "您好", "在吗", "在不在", "嗨", "哈喽", "hello",
    "谢谢", "多谢", "感谢", "再见", "拜拜", "晚安", "早安",
    "嗯", "哦", "啊", "呢", "好的", "行", "可以", "收到",
    "哈哈", "hhh", "233",
}

# 对话行为信号词：出现越多，说明交互轨迹越复杂（高熵候选）
BEHAVIOR_WORDS = (
    "不", "没", "但是", "其实", "而且", "所以", "因为",
    "可是", "不过", "反而", "虽然", "如果", "万一",
    "为什么", "怎么", "难道", "确定", "真的",
)

# 筛网分级阈值
TIER_HIGH = 0.60
TIER_MEDIUM = 0.35
TIER_LOW = 0.15   # 低于此值直接丢弃，不写库


def _shannon_entropy(text: str) -> float:
    """字符级香农熵（bit）。中文场景下字符级已能区分信息密度。"""
    if not text:
        return 0.0
    chars = [c for c in text if not c.isspace()]
    if len(chars) < 2:
        return 0.0
    freq = Counter(chars)
    n = len(chars)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _distinct_ratio(text: str) -> float:
    """词汇丰富度：不同字符数 / 总字符数。"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return len(set(chars)) / len(chars)


def _is_low_info(user_message: str) -> bool:
    t = user_message.strip()
    if len(t) < 4:
        return True
    if not re.search(r"[\w\u4e00-\u9fff]", t):
        return True
    # 去掉标点后，若整句都是寒暄词拼接 → 低信息
    stripped = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    if not stripped:
        return True
    if stripped in LOW_INFO_MARKERS:
        return True
    # 极短且含寒暄词
    if len(stripped) <= 6 and any(m in stripped for m in LOW_INFO_MARKERS):
        return True
    return False

def _frag_repeat_penalty(text: str) -> float:
    """句子碎片化 + 单字重复的惩罚分，0.0 – 0.45。"""
    if not text:
        return 0.0

    sents = [s.strip() for s in re.split(r"[。！？!?\.]", text) if s.strip()]
    n_sent = len(sents)
    avg_len = len(text) / max(n_sent, 1)

    frag = 0.0
    if n_sent >= 4 and avg_len < 8:
        frag = 0.25
    elif n_sent >= 3 and avg_len < 6:
        frag = 0.15

    body = [c for c in text if c not in " \t\n。！？!?，,、；;：:"]
    rep = 0.0
    if body:
        top = Counter(body).most_common(1)[0][1]
        ratio = top / len(body)
        if ratio > 0.15:
            rep = min(0.2, (ratio - 0.15) * 2.0)

    return frag + rep

def compute_entropy_score(user_message: str, ai_reply: str = "") -> dict:
    """
    对每条对话打分，返回：
      score: 0.0-1.0 综合价值分
      tier:  'high' | 'medium' | 'low' | 'drop'
      metrics: 各分项，便于日志和后续调参
    """
    um = user_message.strip()
    ar = ai_reply.strip()

    if _is_low_info(um):
        return {
            "score": 0.0,
            "tier": "drop",
            "metrics": {"reason": "low_info", "user_len": len(um)},
        }

    um_entropy = _shannon_entropy(um)
    um_distinct = _distinct_ratio(um)
    ar_entropy = _shannon_entropy(ar) if ar else 0.0

    # 行为信号：问号 + 否定/转折词 + 多轮迹象（长回复暗示 AI 展开了内容）
    question_cnt = um.count("？") + um.count("?")
    behavior_cnt = sum(1 for w in BEHAVIOR_WORDS if w in um)
    behavior_signals = question_cnt + behavior_cnt
    reply_depth = 1.0 if len(ar) > 40 else (0.5 if len(ar) > 15 else 0.0)

    # 碎片化惩罚：user_message 或 ai_reply 任一碎片化都降权
    penalty = max(_frag_repeat_penalty(um), _frag_repeat_penalty(ar))

    # 分项归一化（经验上限，可按你的数据分布调整）
    len_score = min(len(um) / 80, 1.0)           # 80 字封顶
    entropy_score = min(um_entropy / 4.5, 1.0)   # 中文字符熵常见 3-4.5
    distinct_score = min(um_distinct / 0.85, 1.0)
    behavior_score = min(behavior_signals / 5.0, 1.0)

    # 加权：熵 35% + 长度 25% + 丰富度 15% + 行为 20% + 回复深度 5%
    score = (
        entropy_score * 0.35
        + len_score * 0.25
        + distinct_score * 0.15
        + behavior_score * 0.20
        + reply_depth * 0.05
        - penalty
    )
    score = round(min(max(score, 0.0), 1.0), 4)

    if score >= TIER_HIGH:
        tier = "high"
    elif score >= TIER_MEDIUM:
        tier = "medium"
    elif score >= TIER_LOW:
        tier = "low"
    else:
        tier = "drop"

    return {
        "score": score,
        "tier": tier,
        "metrics": {
            "user_len": len(um),
            "reply_len": len(ar),
            "user_entropy": round(um_entropy, 4),
            "reply_entropy": round(ar_entropy, 4),
            "distinct_ratio": round(um_distinct, 4),
            "behavior_signals": behavior_signals,
            "reply_depth": reply_depth,
        },
    }