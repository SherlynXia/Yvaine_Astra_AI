# backend/core/action_parser.py
"""流式解析 LLM 输出：剥离 () 动作描写 和 [情绪:xxx] 标签"""

import re

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

_STAR_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.S)


class ActionParser:
    """
    流式剥离：
      - () / （） 中的动作描写
      - [] / 【】 中的 [情绪:xxx] 标签
      - **...** 中的动作
    对白通过 feed() 返回，情绪存在 self.emotion。
    """

    def __init__(self):
        self._buffer = ""
        self._paren_depth = 0
        self._pending_action = ""
        self._bracket_depth = 0
        self._pending_bracket = ""
        self.emotion = ""

    def feed(self, chunk: str) -> tuple[str, list[str]]:
        if not chunk:
            return "", []

        self._buffer += chunk
        clean_parts: list[str] = []
        actions: list[str] = []

        for ch in self._buffer:
            # 方括号优先：[] 里的内容不参与 () 解析
            if ch == "[":
                self._bracket_depth += 1
                self._pending_bracket += ch
                continue
            if ch == "]":
                if self._bracket_depth > 0:
                    self._bracket_depth -= 1
                    self._pending_bracket += ch
                    if self._bracket_depth == 0:
                        self._handle_bracket(self._pending_bracket)
                        self._pending_bracket = ""
                    continue
                clean_parts.append(ch)
                continue

            if self._bracket_depth > 0:
                self._pending_bracket += ch
                continue

            # 圆括号：动作描写
            if ch in "（(":
                self._paren_depth += 1
                self._pending_action += ch
                continue
            if ch in "）)":
                if self._paren_depth > 0:
                    self._paren_depth -= 1
                    self._pending_action += ch
                    if self._paren_depth == 0:
                        act = self._pending_action.strip("（）() \n\t")
                        if act:
                            actions.append(act)
                        self._pending_action = ""
                    continue
                clean_parts.append(ch)
                continue

            if self._paren_depth > 0:
                self._pending_action += ch
                continue

            clean_parts.append(ch)

        self._buffer = ""

        clean = "".join(clean_parts)
        star_actions = _STAR_PATTERN.findall(clean)
        clean = _STAR_PATTERN.sub("", clean)
        actions.extend(a.strip() for a in star_actions if a.strip())

        return clean, actions

    def _handle_bracket(self, raw: str):
        """处理一个完整的 [xxx]"""
        content = raw.strip("[]【】 \n\t")
        # 匹配 [情绪:xxx] 或 [情绪：xxx]
        m = re.match(r"^情绪\s*[:：]\s*(.+)$", content)
        if m:
            self.emotion = m.group(1).strip()
        # 其他 [] 内容直接丢弃（不给用户看）

    def flush(self) -> tuple[str, list[str]]:
        """流结束：未闭合的括号/方括号内容全部丢弃"""
        rest = ""
        if self._paren_depth == 0 and self._bracket_depth == 0:
            rest = _STAR_PATTERN.sub("", self._buffer)
        self._buffer = ""
        self._paren_depth = 0
        self._bracket_depth = 0
        self._pending_action = ""
        self._pending_bracket = ""
        return rest, []


def map_action_to_live2d(action_text: str) -> str | None:
    for keyword, tag in _ACTION_HINTS.items():
        if keyword in action_text:
            return tag
    return None