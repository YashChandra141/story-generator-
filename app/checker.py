import re

from .levels import MAX_SENTENCE_LEN, allowed_words

_CURLY_APOSTROPHES = {"\u2018": "'", "\u2019": "'", "\u02bc": "'"}

_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
_SENT_SPLIT_RE = re.compile(r"[.!?\n]+")

_VOWELS = "aeiou"


def normalize(text: str) -> str:
    for curly, plain in _CURLY_APOSTROPHES.items():
        text = text.replace(curly, plain)
    return text.lower()


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize(text))


def sentences(text: str) -> list[str]:
    parts = _SENT_SPLIT_RE.split(normalize(text))
    return [part.strip() for part in parts if part.strip()]


def _dedouble(stem: str) -> str | None:
    if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in _VOWELS:
        return stem[:-1]
    return None


def _base_forms(token: str) -> set[str]:
    if token.endswith("'s"):
        return {token[:-2]} if len(token) > 2 else set()
    forms: set[str] = set()

    def add_stem(stem: str) -> None:
        if not stem:
            return
        forms.add(stem)
        forms.add(stem + "e")
        doubled = _dedouble(stem)
        if doubled:
            forms.add(doubled)

    if token.endswith("es"):
        add_stem(token[:-2])
    if token.endswith("s"):
        forms.add(token[:-1])
    if token.endswith("ed"):
        add_stem(token[:-2])
        if len(token) > 2:
            forms.add(token[:-1])
    if token.endswith("ing"):
        add_stem(token[:-3])
    if token.endswith("er"):
        add_stem(token[:-2])
    return forms


def _token_allowed(token: str, allowed: frozenset[str], extra: set[str], level: int) -> bool:
    if token in allowed or token in extra:
        return True
    if token.endswith("'s"):
        base = token[:-2]
        return base in allowed or base in extra
    if level < 2:
        return False
    return any(base in allowed or base in extra for base in _base_forms(token))


def check(story: str, level: int, extra_words: list[str] | set[str] | None = None) -> dict:
    level = int(level)
    extra = {w.strip().lower() for w in (extra_words or []) if w and w.strip()}
    allowed = allowed_words(level)
    max_len = MAX_SENTENCE_LEN[level]

    toks = tokens(story)
    sents = sentences(story)

    bad = [tok for tok in toks if not _token_allowed(tok, allowed, extra, level)]
    long_sentences = [s for s in sents if len(tokens(s)) > max_len]

    n_words = len(toks)
    in_list = sum(1 for tok in toks if tok in allowed)

    return {
        "ok": not bad and not long_sentences,
        "bad_words": sorted(set(bad)),
        "long_sentences": long_sentences,
        "n_sentences": len(sents),
        "n_words": n_words,
        "in_list_rate": round(in_list / n_words, 3) if n_words else 0.0,
    }
