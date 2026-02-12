from __future__ import annotations

import re

CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_~]+:(\d{6,25})>")
UNICODE_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U000024C2-\U0001F251"
    "](?:\uFE0F|\u200D[\U0001F300-\U0001FAFF\U00002700-\U000027BF])*"
)


def emoji_to_key(emoji: str) -> str:
    return "-".join(f"U+{ord(ch):X}" for ch in emoji)


def extract_emoji_keys(text: str) -> list[str]:
    keys: list[str] = []
    for emoji_id in CUSTOM_EMOJI_RE.findall(text):
        keys.append(f"custom:{emoji_id}")
    for emoji in UNICODE_EMOJI_RE.findall(text):
        keys.append(emoji_to_key(emoji))
    return keys


def reaction_emoji_to_key(emoji) -> str:
    emoji_id = getattr(emoji, "id", None)
    if emoji_id:
        return f"custom:{emoji_id}"
    emoji_name = getattr(emoji, "name", None) or str(emoji)
    return emoji_to_key(emoji_name)
