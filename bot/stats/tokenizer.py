from __future__ import annotations

import re
import string

URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
MENTION_RE = re.compile(r"<(?:@!?\d+|#\d+|@&\d+)>")

STOPWORDS_EN = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "i",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "to", "was", "were", "will", "with",
    "you", "your", "we", "they", "he", "she", "this", "these", "those", "not", "so", "if", "then",
}

STOPWORDS_RU = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все", "она", "так",
    "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по", "только", "ее", "мне", "было",
    "вот", "от", "меня", "еще", "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "ли", "если",
}

DEFAULT_STOPWORDS = STOPWORDS_EN | STOPWORDS_RU
PUNCT_TRANSLATION = str.maketrans({c: " " for c in string.punctuation + "«»„“”—–…"})


def normalize(text: str) -> list[str]:
    cleaned = text.lower()
    cleaned = URL_RE.sub(" ", cleaned)
    cleaned = MENTION_RE.sub(" ", cleaned)
    cleaned = cleaned.translate(PUNCT_TRANSLATION)
    return [tok for tok in cleaned.split() if tok]


def tokenize(
    text: str,
    *,
    min_token_length: int = 3,
    max_tokens_per_message: int = 20,
    stopwords: set[str] | None = None,
) -> list[str]:
    banned = stopwords if stopwords is not None else DEFAULT_STOPWORDS
    tokens: list[str] = []
    for token in normalize(text):
        if len(token) < min_token_length:
            continue
        if token.isnumeric():
            continue
        if token in banned:
            continue
        tokens.append(token)
        if len(tokens) >= max_tokens_per_message:
            break
    return tokens
