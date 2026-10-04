import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from . import levels
from .llm import LLMError, generate_questions, generate_story

load_dotenv()

app = FastAPI(title="word-by-word")

BASE_DIR = Path(__file__).resolve().parents[1]
INDEX_FILE = Path(__file__).resolve().parent / "static" / "index.html"
TOPICS_FILE = BASE_DIR / "data" / "topics.txt"

_NAME_RE = re.compile(r"^[A-Za-z ]+$")
_NEW_WORD_RE = re.compile(r"^[A-Za-z]+$")


class StoryRequest(BaseModel):
    level: int
    child_name: str
    pet_name: str = ""
    new_words: list[str] = []
    topic: str = ""
    n_sentences: int = 6

    @field_validator("level")
    @classmethod
    def check_level(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("level must be between 1 and 5")
        return v

    @field_validator("n_sentences")
    @classmethod
    def check_n_sentences(cls, v: int) -> int:
        if not 4 <= v <= 10:
            raise ValueError("n_sentences must be between 4 and 10")
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
    level: int
    child_name: str
    pet_name: str = ""
    new_words: list[str] = []

    @field_validator("story")
    @classmethod
    def check_story(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("story must not be empty")
        return v

    @field_validator("level")
    @classmethod
    def check_level(cls, v: int) -> int:
        if not 1 <= v <= 5:
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
    return FileResponse(INDEX_FILE)


@app.get("/api/topics")
def topics():
    if not TOPICS_FILE.is_file():
        return []
    return [line.strip() for line in TOPICS_FILE.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


@app.get("/api/placement/{level}")
def placement(level: int):
    if not 1 <= level <= 5:
        raise HTTPException(status_code=400, detail="level must be between 1 and 5")
    return {"words": levels.placement_words(level)}


@app.post("/api/story")
def story(req: StoryRequest):
    try:
        return generate_story(
            req.level,
            req.child_name,
            req.pet_name,
            req.new_words,
            req.topic,
            req.n_sentences,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/questions")
def questions(req: QuestionsRequest):
    try:
        return generate_questions(
            req.story,
            req.level,
            req.child_name,
            req.pet_name,
            req.new_words,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/health")
def health():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
