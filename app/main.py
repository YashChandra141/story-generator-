import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from . import levels
from .llm import LLMError, generate_questions, generate_story
from .tts import TTSError, synthesize_speech

load_dotenv()

app = FastAPI(title="word-by-word")

BASE_DIR = Path(__file__).resolve().parents[1]
INDEX_FILE = Path(__file__).resolve().parent / "static" / "index.html"
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
    return FileResponse(INDEX_FILE)


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
def story(req: StoryRequest):
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
def questions(req: QuestionsRequest):
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


class TTSRequest(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def check_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty")
        if len(v) > 6000:
            raise ValueError("text must be at most 6000 characters")
        return v


@app.post("/api/tts")
def tts(req: TTSRequest):
    try:
        audio = synthesize_speech(req.text)
    except TTSError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return Response(content=audio, media_type="audio/mpeg")


app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
