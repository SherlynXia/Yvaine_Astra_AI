# backend/core/action_parser.py
"""流式解析 LLM 输出：剥离 ()（）* * 中的动作描写"""

import re

# 动作描写里常见的词，用于前端映射
_ACTION_HINTS = {
    "偏头": "tilt_head",
    "歪头": "tilt_head",
    "点头": "nod",
    "摇头": "shake_head",
    "笑": "smile",
    "脸红": "blush",
    "顿了顿": "pause",
    "沉默": "pause",
    "叹气": "sigh",
    "眨眼": "blink",
    "挥手": "wave",
}


class ActionParser:
    """
    流式喂入 chunk，输出 (干净对白, 提取到的动作列表)
    支持 ()、（） 和 **...** 三种包裹形式。
    """

    def __init__(self):
        self.buffer = ""
        self._depth = 0          # 括号嵌套深度
        self._pending_action = ""

    def feed(self, chunk: str) -> tuple[str, list[str]]:
        self.buffer += chunk
        clean_parts: list[str] = []
        actions: list[str] = []
        i = 0
        n = len(self.buffer)

        while i < n:
            ch = self.buffer[i]

            # 进入动作区
            if ch in "（(":
                self._depth += 1
                self._pending_action += ch
                i += 1
                continue
            if ch in "）)":
                if self._depth > 0:
                    self._depth -= 1
                    self._pending_action += ch
                    if self._depth == 0:
                        act = self._pending_action.strip("（）() ")
                        if act:
                            actions.append(act)
                        self._pending_action = ""
                    i += 1
                    continue

            if self._depth > 0:
                self._pending_action += ch
                i += 1
                continue

            # 普通对白
            clean_parts.append(ch)
            i += 1

        self.buffer = ""
        clean = "".join(clean_parts)

        # **...** 形式单独用正则处理（简单场景够用）
        clean, star_actions = self._extract_star(clean)
        actions.extend(star_actions)

        return clean, actions

    def _extract_star(self, text: str) -> tuple[str, list[str]]:
        pattern = re.compile(r"\*\*(.+?)\*\*", re.S)
        found = pattern.findall(text)
        cleaned = pattern.sub("", text)
        return cleaned, [f.strip() for f in found if f.strip()]

    def flush(self) -> tuple[str, list[str]]:
        """流结束，把未闭合的残留当对白吐出"""
        rest = self.buffer
        if self._depth > 0:
            # 未闭合括号：丢弃内容，避免 TTS 读半个动作
            rest = ""
        self.buffer = ""
        self._depth = 0
        self._pending_action = ""
        return rest, []


def map_action_to_live2d(action_text: str) -> str | None:
    """把动作文本映射成前端能识别的 tag，匹配不到返回 None"""
    for keyword, tag in _ACTION_HINTS.items():
        if keyword in action_text:
            return tag
    return None