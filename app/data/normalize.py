import re

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")
_DIGIT_RE = re.compile(r"\b\d+\b")

_STOPWORDS = {
    "the", "of", "for", "and", "to", "in", "at", "a", "an", "on", "with",
    "supply", "procurement", "provision", "purchase",
}


def peer_group_key(text: str | None) -> str | None:
    """Normalize free-text item/tender descriptions into a coarse grouping key
    used for peer price comparisons, since the dataset has no classification codes.
    """
    if not text:
        return None
    t = text.lower()
    t = _DIGIT_RE.sub(" ", t)
    t = _NON_ALNUM_RE.sub(" ", t)
    tokens = [tok for tok in t.split() if tok not in _STOPWORDS and len(tok) > 2]
    if not tokens:
        return None
    tokens = sorted(set(tokens))[:6]
    return " ".join(tokens)
