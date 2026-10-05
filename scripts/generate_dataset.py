"""Build data/train.jsonl for fine-tuning a small model on SHORT-prompt stories."""

import argparse
import json
import random
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app import levels, llm
from app.llm import LLMError, generate_story

TRAIN_PATH = ROOT / "data" / "train.jsonl"
META_PATH = ROOT / "data" / "train_meta.jsonl"
TOPICS_PATH = ROOT / "data" / "train_topics.txt"
TOPICS_FILE = ROOT / "data" / "topics.txt"

NEW_WORD_POOL = [
    "kite", "mango", "bus", "train", "bat", "sky", "moon", "star",
    "park", "cake", "rain", "tree", "boat", "ball", "hat",
]

TOPIC_PROMPT = (
    "List 150 short, kind story topics for Indian children aged 5-10.\n"
    "One topic per line, maximum 8 words per topic, no names, nothing scary.\n"
    "Output only the list, one topic per line, nothing else."
)

BACKOFF_ATTEMPTS = 6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build data/train.jsonl for fine-tuning.")
    parser.add_argument("--target", type=int, default=800, help="total examples to keep in train.jsonl")
    parser.add_argument("--dry-run", type=int, default=0, metavar="N", help="print N examples without saving")
    return parser.parse_args()


def eval_topics() -> set[str]:
    if not TOPICS_FILE.is_file():
        return set()
    lines = [
        line.strip().lower()
        for line in TOPICS_FILE.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    return set(lines[-4:])


def count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def status_of(exc: Exception) -> int | None:
    status = getattr(exc.__cause__, "status_code", None)
    return status if isinstance(status, int) else None


def retryable(status: int | None) -> bool:
    return status == 429 or (status is not None and 500 <= status < 600)


def call_with_backoff(client, model, messages, temperature, max_tokens):
    delay = 2.0
    last_exc = None
    for _ in range(BACKOFF_ATTEMPTS):
        try:
            return llm._call(client, model, messages, temperature, max_tokens)
        except LLMError as exc:
            if not retryable(status_of(exc)):
                raise
            last_exc = exc
            print(f"  status {status_of(exc)} - backing off {delay:.0f}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise last_exc


def generate_with_backoff(params: dict) -> dict:
    delay = 2.0
    last_exc = None
    for _ in range(BACKOFF_ATTEMPTS):
        try:
            return generate_story(**params)
        except LLMError as exc:
            if not retryable(status_of(exc)):
                raise
            last_exc = exc
            print(f"  status {status_of(exc)} - backing off {delay:.0f}s...")
            time.sleep(delay)
            delay = min(delay * 2, 60)
    raise last_exc


def ensure_train_topics() -> list[str]:
    if TOPICS_PATH.is_file():
        return [
            line.strip()
            for line in TOPICS_PATH.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    print("data/train_topics.txt not found - asking the model for topics...")
    client = llm.make_client()
    model_name = llm._model_name(None)
    max_tokens = max(2000, llm._env_int("LLM_MAX_TOKENS", 1000))
    text, _ = call_with_backoff(
        client, model_name, [{"role": "user", "content": TOPIC_PROMPT}], 0.8, max_tokens
    )
    banned = eval_topics()
    seen = set()
    topics = []
    for line in text.splitlines():
        topic = " ".join(line.strip().split()).lower()
        if not topic or topic in seen or topic in banned:
            continue
        seen.add(topic)
        topics.append(topic)
    if not topics:
        raise SystemExit("The model returned no usable topics.")
    TOPICS_PATH.write_text("\n".join(topics) + "\n", encoding="utf-8")
    print(f"Saved {len(topics)} topics to {TOPICS_PATH.name}")
    return topics


def next_params(rng: random.Random, topics: list[str]) -> dict:
    level = rng.randint(1, 5)
    pool = [w for w in NEW_WORD_POOL if w not in levels.allowed_words(level)]
    n_new = rng.randint(0, 2)
    return {
        "level": level,
        "child_name": "Asha",
        "pet_name": "Moti" if rng.random() < 0.5 else "",
        "new_words": rng.sample(pool, min(n_new, len(pool))),
        "topic": rng.choice(topics),
        "n_sentences": rng.randint(4, 8),
        "prompt_style": "full",
    }


def build_example(params: dict, result: dict) -> dict:
    messages = llm._story_messages(
        "short",
        params["level"],
        params["new_words"],
        params["topic"],
        params["pet_name"],
        params["n_sentences"],
    )
    return {
        "messages": [
            {"role": "system", "content": messages[0]["content"]},
            {"role": "user", "content": messages[1]["content"]},
            {"role": "assistant", "content": result["story_placeholder"]},
        ]
    }


def print_progress(tried: int, kept: int, stats: dict) -> None:
    parts = []
    for lv in range(1, 6):
        k, t = stats[lv]
        rate = f"{100 * k / t:.0f}%" if t else "-"
        parts.append(f"L{lv} {k}/{t} ({rate})")
    overall = f"{100 * kept / tried:.0f}%" if tried else "-"
    print(f"[tried {tried}] kept {kept} ({overall}) | " + "  ".join(parts))


def dry_run(args: argparse.Namespace, topics: list[str]) -> int:
    rng = random.Random(123)
    kept = 0
    tried = 0
    cap = max(args.dry_run * 10, 20)
    while kept < args.dry_run and tried < cap:
        params = next_params(rng, topics)
        tried += 1
        try:
            result = generate_with_backoff(params)
        except LLMError as exc:
            print(f"  [dry {tried}] skipped: {exc}")
            continue
        if not result["ok"]:
            print(f"  [dry {tried}] not ok (attempts={result['attempts']}), skipped")
            continue
        print(json.dumps(build_example(params, result), ensure_ascii=False))
        kept += 1
    print(f"Dry run: printed {kept} example(s) from {tried} try(ies). Nothing saved.")
    return 0


def run(args: argparse.Namespace, topics: list[str]) -> int:
    existing = count_lines(TRAIN_PATH)
    remaining = args.target - existing
    print(
        f"{TRAIN_PATH.name} has {existing} example(s); target {args.target}; "
        f"generating {max(0, remaining)} more."
    )
    if remaining <= 0:
        return 0

    rng = random.Random(123)
    kept = 0
    tried = 0
    failures = 0
    stats = {lv: [0, 0] for lv in range(1, 6)}
    printed_at = 0

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        with TRAIN_PATH.open("a", encoding="utf-8") as train_fh, META_PATH.open(
            "a", encoding="utf-8"
        ) as meta_fh:
            while kept < remaining:
                while len(futures) < 4:
                    params = next_params(rng, topics)
                    futures[executor.submit(generate_with_backoff, params)] = params
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for fut in done:
                    params = futures.pop(fut)
                    tried += 1
                    stats[params["level"]][1] += 1
                    try:
                        result = fut.result()
                    except LLMError as exc:
                        failures += 1
                        print(f"  skipped level {params['level']}: {exc}")
                        if failures >= 40:
                            raise SystemExit(
                                "Too many consecutive failures - stopping. Check the model settings."
                            )
                        continue
                    failures = 0
                    if not result["ok"]:
                        continue
                    train_fh.write(json.dumps(build_example(params, result), ensure_ascii=False) + "\n")
                    train_fh.flush()
                    meta = {
                        "level": params["level"],
                        "topic": params["topic"],
                        "attempts": result["attempts"],
                        "first_try_ok": result["first_try_ok"],
                    }
                    meta_fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
                    meta_fh.flush()
                    kept += 1
                    stats[params["level"]][0] += 1
                if tried - printed_at >= 10:
                    print_progress(tried, kept, stats)
                    printed_at = tried

    print(f"Done: {kept} new example(s) in {TRAIN_PATH.name} from {tried} try(ies).")
    print_progress(tried, kept, stats)
    return 0


def main() -> int:
    args = parse_args()
    topics = ensure_train_topics()
    if not topics:
        print("No training topics available.")
        return 1
    if args.dry_run:
        return dry_run(args, topics)
    return run(args, topics)


if __name__ == "__main__":
    sys.exit(main())
