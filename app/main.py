import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from . import levels
from .llm import LLMError, generate_questions, generate_story

load_dotenv()

# Docs/redoc/openapi are disabled: the public site exposes only the app itself.
app = FastAPI(title="word-by-word", docs_url=None, redoc_url=None, openapi_url=None)

# CORS for the Next.js frontend (ui/). Comma-separated origins, e.g.
# CORS_ORIGINS=https://word-by-word-ui.onrender.com
_CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

BASE_DIR = Path(__file__).resolve().parents[1]
TOPICS_FILE = BASE_DIR / "data" / "topics.txt"

_NAME_RE = re.compile(r"^[A-Za-z ]+$")
_NEW_WORD_RE = re.compile(r"^[A-Za-z]+$")


class StoryRequest(BaseModel):
    level: int | None = None
    child_name: str
    pet_name: str = ""
    new_words: list[str] = []
    known_words: list[str] = []
    topic: str = ""
    n_sentences: int = 6

    @field_validator("level")
    @classmethod
    def check_level(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 5:
            raise ValueError("level must be between 1 and 5")
        return v

    @field_validator("n_sentences")
    @classmethod
    def check_n_sentences(cls, v: int) -> int:
        if not 4 <= v <= 120:
            raise ValueError("n_sentences must be between 4 and 120")
        return v

    @field_validator("new_words")
    @classmethod
    def check_new_words(cls, v: list[str]) -> list[str]:
        if len(v) > 3:
            raise ValueError("at most 3 new words")
        for word in v:
            if not _NEW_WORD_RE.fullmatch(word):
                raise ValueError("new words must use letters only")
        return v

    @field_validator("known_words")
    @classmethod
    def check_known_words(cls, v: list[str]) -> list[str]:
        if len(v) > 300:
            raise ValueError("at most 300 known words")
        for word in v:
            if not _NEW_WORD_RE.fullmatch(word):
                raise ValueError("known words must use letters only")
        return [w.strip().lower() for w in v if w.strip()]

    @field_validator("child_name", "pet_name")
    @classmethod
    def check_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 20:
            raise ValueError("names must be at most 20 characters")
        if v and not _NAME_RE.fullmatch(v):
            raise ValueError("names must use letters and spaces only")
        return v

    @field_validator("topic")
    @classmethod
    def check_topic(cls, v: str) -> str:
        if len(v) > 200:
            raise ValueError("topic must be at most 200 characters")
        return v.strip()


class QuestionsRequest(BaseModel):
    story: str
    level: int | None = None
    child_name: str
    pet_name: str = ""
    new_words: list[str] = []
    known_words: list[str] = []
    learning_goal: str = ""
    n_questions: int = 3

    @field_validator("n_questions")
    @classmethod
    def check_n_questions(cls, v: int) -> int:
        if not 1 <= v <= 12:
            raise ValueError("n_questions must be between 1 and 12")
        return v

    @field_validator("story")
    @classmethod
    def check_story(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("story must not be empty")
        return v

    @field_validator("level")
    @classmethod
    def check_level(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 5:
            raise ValueError("level must be between 1 and 5")
        return v

    @field_validator("new_words")
    @classmethod
    def check_new_words(cls, v: list[str]) -> list[str]:
        if len(v) > 3:
            raise ValueError("at most 3 new words")
        for word in v:
            if not _NEW_WORD_RE.fullmatch(word):
                raise ValueError("new words must use letters only")
        return v

    @field_validator("known_words")
    @classmethod
    def check_known_words(cls, v: list[str]) -> list[str]:
        if len(v) > 300:
            raise ValueError("at most 300 known words")
        for word in v:
            if not _NEW_WORD_RE.fullmatch(word):
                raise ValueError("known words must use letters only")
        return [w.strip().lower() for w in v if w.strip()]

    @field_validator("child_name", "pet_name")
    @classmethod
    def check_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 20:
            raise ValueError("names must be at most 20 characters")
        if v and not _NAME_RE.fullmatch(v):
            raise ValueError("names must use letters and spaces only")
        return v


@app.get("/")
def index():
    # API-only backend: status ping, the interface lives in the Next.js frontend
    return {"app": "word-by-word", "ok": True, "up": "yes"}


@app.get("/api/topics")
def topics():
    if not TOPICS_FILE.is_file():
        return []
    return [line.strip() for line in TOPICS_FILE.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


@app.get("/api/wordbank")
def wordbank():
    return {"tiers": [dict(t) for t in levels.word_bank()]}


@app.get("/api/placement/{level}")
def placement(level: int):
    if not 1 <= level <= 5:
        raise HTTPException(status_code=400, detail="level must be between 1 and 5")
    return {"words": levels.placement_words(level)}


@app.post("/api/story")
def story(req: StoryRequest, request: Request):
    _reject_if_limited(request)
    level = req.level if req.level is not None else levels.infer_level(req.known_words)
    try:
        return generate_story(
            level,
            req.child_name,
            req.pet_name,
            req.new_words,
            req.topic,
            req.n_sentences,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/questions")
def questions(req: QuestionsRequest, request: Request):
    _reject_if_limited(request)
    level = req.level if req.level is not None else levels.infer_level(req.known_words)
    try:
        return generate_questions(
            req.story,
            level,
            req.child_name,
            req.pet_name,
            req.new_words,
            learning_goal=req.learning_goal,
            n_questions=req.n_questions,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/health")
def health():
    return {"ok": True}


# ---- simple per-IP rate limit on the paid endpoints (story/questions) ----
try:
    _RATE_LIMIT = max(1, int(os.getenv("RATE_LIMIT_PER_MIN", "20")))
except ValueError:
    _RATE_LIMIT = 20
_hits: dict[str, deque] = defaultdict(deque)
_LAST_PRUNE = 0.0


def _client_ip(request: Request) -> str:
    # Trust only the RIGHTMOST X-Forwarded-For entry: our reverse proxy
    # (Render) APPENDS the real client IP, while anything to the left was
    # sent by the client itself and can be spoofed. Falling back to the
    # direct socket IP when no proxy header exists (local dev).
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _rate_limited(request: Request) -> bool:
    global _LAST_PRUNE
    now = time.monotonic()
    # Prune stale buckets periodically instead of clearing everything, so a
    # flood of unique IPs cannot flush the limiter and reset everyone's quota.
    if len(_hits) > 5000 and now - _LAST_PRUNE > 60:
        for ip in [
            ip
            for ip, h in _hits.items()
            if not h or now - h[-1] > 60
        ]:
            _hits.pop(ip, None)
        _LAST_PRUNE = now
    hits = _hits[_client_ip(request)]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= _RATE_LIMIT:
        return True
    hits.append(now)
    return False


def _reject_if_limited(request: Request) -> None:
    if _rate_limited(request):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")
