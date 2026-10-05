import json
import os
import re

from dotenv import load_dotenv
from openai import APIError, OpenAI

from . import checker, prompts
from .levels import allowed_words

load_dotenv()

_THINK_OPEN = chr(60) + "think" + chr(62)
_THINK_CLOSE = chr(60) + "/think" + chr(62)
_THINK_RE = re.compile(_THINK_OPEN + ".*?" + _THINK_CLOSE, re.DOTALL)


class LLMError(RuntimeError):
    pass


def make_client(base_url: str | None = None, api_key: str | None = None) -> OpenAI:
    return OpenAI(
        base_url=base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key or os.getenv("LLM_API_KEY", "missing-key"),
        timeout=120.0,
    )


def _fmt(template: str, **kwargs) -> str:
    out = template
    for key, value in kwargs.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _clean(text: str) -> str:
    text = _THINK_RE.sub("", text or "")
    return text.strip()


def _replace_word(text: str, old: str, new: str, case_sensitive: bool = True) -> str:
    if not old or not text:
        return text
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = re.compile(r"\b" + re.escape(old) + r"('s)?\b", flags)
    return pattern.sub(lambda m: new + (m.group(1) or "").lower(), text)


def _pick_style(prompt_style: str | None) -> str:
    style = (prompt_style or os.getenv("PROMPT_STYLE") or "full").strip().lower()
    return style if style in ("full", "short") else "full"


def _model_name(model: str | None) -> str:
    name = (model or os.getenv("LLM_MODEL") or "").strip()
    if not name:
        raise LLMError("No model is configured. Set LLM_MODEL in your .env file.")
    return name


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _message_text(message) -> str:
    if message is None:
        return ""
    candidates = [
        getattr(message, "content", None),
        getattr(message, "reasoning_content", None),
        getattr(message, "reasoning", None),
    ]
    extra = getattr(message, "model_extra", None) or {}
    if isinstance(extra, dict):
        candidates.append(extra.get("reasoning_content"))
        candidates.append(extra.get("reasoning"))
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _call(client: OpenAI, model: str, messages: list, temperature: float, max_tokens: int) -> tuple[str, int | None]:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    except APIError as exc:
        raise LLMError("The story service had trouble responding. Please try again in a moment.") from exc
    except Exception as exc:
        raise LLMError("Could not reach the story service. Please check your connection and try again.") from exc
    content = ""
    if response.choices:
        content = _message_text(response.choices[0].message)
    content = _clean(content)
    if not content:
        raise LLMError("The model returned no text. Please try again.")
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    return content, prompt_tokens


def _new_words_list(new_words) -> list[str]:
    out = []
    for word in new_words or []:
        word = str(word).strip().lower()
        if word and word not in out:
            out.append(word)
    return out


def _apply_names(placeholder: str, child_name: str, pet_name: str) -> str:
    text = _replace_word(placeholder, "MINU", child_name or "the child", case_sensitive=False)
    pet_text = pet_name.strip() if pet_name and pet_name.strip() else "the pet"
    return _replace_word(text, "PIP", pet_text, case_sensitive=False)


_QUESTION_MARK_STARTERS = (
    "what", "why", "who", "where", "when", "how",
    "is", "are", "can", "do", "does", "did", "will",
)


_PAST_WORDS = {
    "went", "saw", "ran", "was", "were", "had", "got", "sat", "flew", "ate",
    "came", "took", "made", "said", "did", "found", "gave", "told", "felt",
    "left", "met", "put", "hid", "swam", "sang", "fell", "heard", "kept",
    "held", "stood", "thought", "brought", "bought", "caught", "slept",
    "woke", "rode", "wore", "won", "lost", "became", "began", "broke",
    "drew", "drove", "grew", "knew", "led", "paid", "rose", "spoke", "threw",
    "wrote", "played", "jumped", "walked", "looked", "wanted", "helped",
    "asked", "called", "opened", "washed", "hopped", "skipped", "smiled",
    "laughed", "shouted", "waited", "picked", "showed", "turned", "stopped",
}

_NON_PAST_ED = {"red", "bed", "seed", "need", "feed", "speed", "bleed", "deed"}

_PRESENT_WORDS = {
    "is", "are", "am", "has", "have", "does", "goes", "sees", "plays", "runs",
    "jumps", "likes", "wants", "looks", "comes", "eats", "helps", "walks",
    "sits", "says", "makes", "takes", "gives", "finds", "tells", "shows",
    "knows", "reads", "lives", "loves", "wears", "flies", "cries", "tries",
    "washes", "watches", "holds", "stands", "sings", "drinks", "thinks",
    "sleeps", "meets", "needs", "feeds", "gets", "puts", "hides", "swims",
}


def _tense_mixed(text: str) -> bool:
    """True when some sentences are past tense and others are present tense."""
    parts = re.split(r"[.!?\n]+", (text or "").lower())
    past = present = 0
    for part in parts:
        toks = set(re.findall(r"[a-z']+", part))
        is_past = any(
            t in _PAST_WORDS or (t.endswith("ed") and t not in _NON_PAST_ED)
            for t in toks
        )
        is_present = any(t in _PRESENT_WORDS for t in toks)
        if is_past:
            past += 1
        if is_present:
            present += 1
    return past > 0 and present > 0


def _fix_articles(text: str) -> str:
    """Deterministic article agreement: 'a' before vowel sounds -> 'an',
    'an' before consonant sounds -> 'a'. Keeps the article's case."""
    def _keep_case(new_word: str, old_word: str) -> str:
        return new_word.capitalize() if old_word[0].isupper() else new_word

    text = re.sub(
        r"\b([Aa])\s+([aeiou][a-z]+)\b",
        lambda m: _keep_case("an", m.group(1)) + " " + m.group(2),
        text,
    )
    text = re.sub(
        r"\b([Aa]n)\s+([bcdfghjklmnpqrstvwxyz][a-z]+)\b",
        lambda m: _keep_case("a", m.group(1)) + " " + m.group(2),
        text,
    )
    return text


def _fix_punctuation(text: str, default_mark: str = ".") -> str:
    """Tidy basic punctuation and articles: one sentence per line kept, each
    sentence gets a terminal mark, a space after (and none before) punctuation,
    a capital first letter, and a/an agreement. Standalone lowercase i becomes I."""
    text = (text or "").strip()
    if not text:
        return text
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw.strip())
        if not line:
            continue
        line = _fix_articles(line)
        line = re.sub(r"\s+([,.!?;:])", r"\1", line)
        line = re.sub(r"([,.!?;:])(?=[A-Za-z])", r"\1 ", line)
        if not re.search(r"[.!?]$", line):
            line = line.rstrip(" ,;:") + default_mark
        lines.append(line)
    joined = "\n".join(lines)
    parts = re.split(r"([.!?\n]+)", joined)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        m = re.search(r"[A-Za-z]", seg)
        if m:
            parts[i] = seg[: m.start()] + seg[m.start()].upper() + seg[m.start() + 1 :]
    fixed = "".join(parts[i] + (parts[i + 1] if i + 1 < len(parts) else "") for i in range(0, len(parts), 2))
    return re.sub(r"\bi\b", "I", fixed)


def _fill_system(style: str, level: int, new_words: list[str], n_sentences: int) -> str:
    template = prompts.SHORT_SYSTEM if style == "short" else prompts.STORY_SYSTEM
    return _fmt(
        template,
        extra_list=(", " + ", ".join(new_words)) if new_words else "",
        max_len=checker.MAX_SENTENCE_LEN[level],
        n_sentences=n_sentences,
        new_words_rule=(
            "Use each of these new words at least two times: " + ", ".join(new_words) + "."
            if new_words
            else "Use simple, common words."
        ),
        allowed_words=", ".join(sorted(allowed_words(level))),
    )


def _story_messages(
    style: str, level: int, new_words: list[str], topic: str, pet_name: str, n_sentences: int
) -> list:
    system = _fill_system(style, level, new_words, n_sentences)
    if style == "short":
        user = _fmt(
            prompts.SHORT_USER,
            level=level,
            max_len=checker.MAX_SENTENCE_LEN[level],
            n_sentences=n_sentences,
            new_words_or_none=", ".join(new_words) or "none",
            pet_or_none="PIP" if pet_name else "none",
            topic=topic,
        )
    else:
        pet_line = "\nMINU has a pet called PIP." if pet_name else ""
        user = _fmt(prompts.STORY_USER, topic=topic, pet_line=pet_line)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_story(
    level,
    child_name: str,
    pet_name: str,
    new_words,
    topic: str,
    n_sentences: int,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    prompt_style: str | None = None,
) -> dict:
    level = int(level)
    n_sentences = int(n_sentences)
    style = _pick_style(prompt_style)
    model_name = _model_name(model)
    client = make_client(base_url, api_key)
    # Scale the completion budget with the requested story length so long
    # stories never get truncated (1 token ~= 0.75 words).
    max_tokens = max(_env_int("LLM_MAX_TOKENS", 1000), n_sentences * 25 + 100)
    max_rewrites = _env_int("MAX_REWRITES", 1)

    child = (child_name or "").strip()
    pet = (pet_name or "").strip()
    words = _new_words_list(new_words)
    clean_topic = (topic or "").strip() or "a happy day"
    extras = {w.lower() for w in (child, pet, *words) if w}

    messages = _story_messages(style, level, words, clean_topic, pet, n_sentences)
    prompt_chars = sum(len(m["content"]) for m in messages)

    text, prompt_tokens = _call(client, model_name, messages, 0.7, max_tokens)
    placeholder = _fix_punctuation(text)
    real = _apply_names(placeholder, child, pet)
    report = checker.check(real, level, extras)

    tense_flag = _tense_mixed(real)
    first_try_ok = report["ok"] and report["n_sentences"] == n_sentences and not tense_flag
    first_draft = real
    attempts = 1
    story, story_placeholder = real, placeholder

    for _ in range(max_rewrites):
        tense_flag = _tense_mixed(real)
        if report["ok"] and report["n_sentences"] == n_sentences and not tense_flag:
            break
        ph_report = checker.check(placeholder, level, extras | {"minu", "pip"})
        count_now = report["n_sentences"]
        count_line = (
            f"It has {count_now} sentences, but it must have exactly {n_sentences}."
            if count_now != n_sentences
            else "The sentence count is correct."
        )
        tense_line = (
            "It mixes past tense and present tense. Use one tense for the whole story."
            if _tense_mixed(placeholder)
            else "The tenses are consistent."
        )
        rewrite_tpl = prompts.REWRITE_SHORT if style == "short" else prompts.REWRITE_FULL
        rewrite = _fmt(
            rewrite_tpl,
            bad_words=", ".join(ph_report["bad_words"]) or "none",
            long_sentences=" | ".join(ph_report["long_sentences"]) or "none",
            count_line=count_line,
            tense_line=tense_line,
            n_sentences=n_sentences,
        )
        messages.append({"role": "assistant", "content": placeholder})
        messages.append({"role": "user", "content": rewrite})
        text, _ = _call(client, model_name, messages, 0.3, max_tokens)
        attempts += 1
        placeholder = _fix_punctuation(text)
        real = _apply_names(placeholder, child, pet)
        report = checker.check(real, level, extras)
        story, story_placeholder = real, placeholder

    return {
        "story": story,
        "story_placeholder": story_placeholder,
        "level": level,
        "ok": report["ok"] and report["n_sentences"] == n_sentences and not _tense_mixed(story),
        "first_try_ok": first_try_ok,
        "attempts": attempts,
        "first_draft": first_draft,
        "report": report,
        "prompt_tokens": prompt_tokens if prompt_tokens is not None else max(1, prompt_chars // 4),
    }


def _parse_questions(text: str) -> list[dict]:
    text = _clean(text)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                out = []
                for item in data:
                    if isinstance(item, dict) and item.get("q") and item.get("a"):
                        out.append({"q": str(item["q"]).strip(), "a": str(item["a"]).strip()})
                if out:
                    return out
        except ValueError:
            pass
    out = []
    current = None
    for line in text.splitlines():
        line = line.strip()
        q_match = re.match(r"^(?:q|question)\s*[:.)]\s*(.+)$", line, re.IGNORECASE)
        a_match = re.match(r"^(?:a|answer)\s*[:.)]\s*(.+)$", line, re.IGNORECASE)
        if q_match:
            current = q_match.group(1).strip()
        elif a_match and current:
            out.append({"q": current, "a": a_match.group(1).strip()})
            current = None
    return out


def generate_questions(
    story: str,
    level,
    child_name: str,
    pet_name: str,
    new_words,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    prompt_style: str | None = None,
    learning_goal: str = "",
    n_questions: int = 3,
) -> list[dict]:
    level = int(level)
    style = _pick_style(prompt_style)
    model_name = _model_name(model)
    client = make_client(base_url, api_key)
    max_tokens = _env_int("LLM_MAX_TOKENS", 1000)
    n_questions = max(1, min(12, int(n_questions)))
    goal_line = prompts.QUESTION_GOALS.get((learning_goal or "").strip().lower(), prompts.QUESTION_GOALS["comprehension"])

    child = (child_name or "").strip()
    pet = (pet_name or "").strip()
    words = _new_words_list(new_words)
    extras = {w.lower() for w in (child, pet, *words) if w}

    story_for_model = _replace_word(
        _replace_word(story or "", child, "MINU", case_sensitive=False), pet, "PIP", case_sensitive=False
    )
    names_line = " and the name MINU"
    if pet:
        names_line = " and the names MINU and PIP"
    messages = [
        {"role": "system", "content": _fill_system(style, level, words, 3)},
        {
            "role": "user",
            "content": _fmt(
                prompts.QUESTIONS_USER,
                story=story_for_model,
                names_line=names_line,
                n_questions=n_questions,
                goal_line=goal_line,
            ),
        },
    ]

    text, _ = _call(client, model_name, messages, 0.5, max_tokens)
    questions = _parse_questions(text)

    out = []
    for item in questions:
        mark = "?" if item["q"].strip().lower().startswith(_QUESTION_MARK_STARTERS) else "."
        q = _fix_punctuation(_apply_names(item["q"], child, pet), default_mark=mark)
        a = _fix_punctuation(_apply_names(item["a"], child, pet))
        if checker.check(q, level, extras)["ok"]:
            out.append({"q": q, "a": a})
    return out
