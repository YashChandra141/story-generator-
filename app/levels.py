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
