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
        timeout=60.0,
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
    max_tokens = _env_int("LLM_MAX_TOKENS", 1000)
    max_rewrites = _env_int("MAX_REWRITES", 1)

    child = (child_name or "").strip()
    pet = (pet_name or "").strip()
    words = _new_words_list(new_words)
    clean_topic = (topic or "").strip() or "a happy day"
    extras = {w.lower() for w in (child, pet, *words) if w}

    messages = _story_messages(style, level, words, clean_topic, pet, n_sentences)
    prompt_chars = sum(len(m["content"]) for m in messages)

    text, prompt_tokens = _call(client, model_name, messages, 0.7, max_tokens)
    placeholder = text
    real = _apply_names(placeholder, child, pet)
    report = checker.check(real, level, extras)

    first_try_ok = report["ok"]
    first_draft = real
    attempts = 1
    story, story_placeholder = real, placeholder

    for _ in range(max_rewrites):
        if report["ok"]:
            break
        ph_report = checker.check(placeholder, level, extras | {"minu", "pip"})
        rewrite_tpl = prompts.REWRITE_SHORT if style == "short" else prompts.REWRITE_FULL
        rewrite = _fmt(
            rewrite_tpl,
            bad_words=", ".join(ph_report["bad_words"]) or "none",
            long_sentences=" | ".join(ph_report["long_sentences"]) or "none",
            n_sentences=n_sentences,
        )
        messages.append({"role": "assistant", "content": placeholder})
        messages.append({"role": "user", "content": rewrite})
        text, _ = _call(client, model_name, messages, 0.3, max_tokens)
        attempts += 1
        placeholder = text
        real = _apply_names(placeholder, child, pet)
        report = checker.check(real, level, extras)
        story, story_placeholder = real, placeholder

    return {
        "story": story,
        "story_placeholder": story_placeholder,
        "ok": report["ok"],
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
) -> list[dict]:
    level = int(level)
    style = _pick_style(prompt_style)
    model_name = _model_name(model)
    client = make_client(base_url, api_key)
    max_tokens = _env_int("LLM_MAX_TOKENS", 1000)

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
        {"role": "user", "content": _fmt(prompts.QUESTIONS_USER, story=story_for_model, names_line=names_line)},
    ]

    text, _ = _call(client, model_name, messages, 0.5, max_tokens)
    questions = _parse_questions(text)

    out = []
    for item in questions:
        q = _apply_names(item["q"], child, pet)
        a = _apply_names(item["a"], child, pet)
        if checker.check(q, level, extras)["ok"]:
            out.append({"q": q, "a": a})
    return out
