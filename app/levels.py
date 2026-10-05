import random
import re
from functools import lru_cache
from pathlib import Path

from wordfreq import top_n_list

LEVELS_DIR = Path(__file__).resolve().parents[1] / "data" / "levels"

LEVEL_FILES = {
    1: ("preprimer.txt", "primer.txt", "nouns.txt", "everyday.txt"),
    2: ("grade1.txt",),
    3: ("grade2.txt",),
    4: ("grade3.txt",),
    5: (),
}

_FREQ_RE = re.compile(r"^[a-z]+('[a-z]+)?$")

MAX_SENTENCE_LEN = {1: 6, 2: 8, 3: 10, 4: 12, 5: 14}


@lru_cache(maxsize=None)
def file_words(name: str) -> frozenset[str]:
    path = LEVELS_DIR / name
    if not path.is_file():
        return frozenset()
    words = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        for token in line.split():
            token = token.lower()
            if token:
                words.add(token)
    return frozenset(words)


@lru_cache(maxsize=None)
def _freq_words() -> frozenset[str]:
    words = set()
    for word in top_n_list("en", 1500):
        word = word.lower()
        if len(word) >= 2 and _FREQ_RE.match(word):
            words.add(word)
    words.update({"a", "i"})
    return frozenset(words)


@lru_cache(maxsize=None)
def allowed_words(level: int) -> frozenset[str]:
    level = int(level)
    if level < 1:
        return frozenset()
    words = set()
    for name in LEVEL_FILES[1]:
        words |= file_words(name)
    if level >= 2:
        words |= file_words("grade1.txt")
    if level >= 3:
        words |= file_words("grade2.txt")
    if level >= 4:
        words |= file_words("grade3.txt")
    if level >= 5:
        words |= _freq_words()
    return frozenset(words)


def placement_words(level: int) -> list[str]:
    level = int(level)
    current = allowed_words(level)
    if level > 1:
        new_words = sorted(current - allowed_words(level - 1))
    else:
        new_words = sorted(current)
    rng = random.Random(42)
    return rng.sample(new_words, min(10, len(new_words)))


# ---------------------------------------------------------------- word bank --
# Checkbox-based assessment: the parent ticks the words the child can read.

TIER_DEFS = [
    (1, "First words", 16),
    (2, "Grade 1", 14),
    (3, "Grade 2", 12),
    (4, "Grade 3", 10),
    (5, "Everyday reader", 12),
]


@lru_cache(maxsize=None)
def word_bank() -> tuple[dict, ...]:
    """Deterministic sample of words per tier for the 'words they know' check."""
    tiers: list[dict] = []
    prev = frozenset()
    for tier, name, n in TIER_DEFS:
        pool = sorted(allowed_words(tier) - prev)
        pool = [w for w in pool if 2 <= len(w) <= 10 and "'" not in w]
        rng = random.Random(100 + tier)
        words = rng.sample(pool, min(n, len(pool)))
        tiers.append({"tier": tier, "name": name, "words": words})
        prev = allowed_words(tier)
    return tuple(tiers)


def infer_level(known_words) -> int:
    """Map the ticked words to the reading level the app should use."""
    known = {str(w).strip().lower() for w in (known_words or []) if str(w).strip()}
    for tier in (5, 4, 3, 2):
        sample = next((t["words"] for t in word_bank() if t["tier"] == tier), [])
        if sample and sum(1 for w in sample if w in known) / len(sample) >= 0.5:
            return tier
    return 1
