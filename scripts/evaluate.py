"""Evaluate story generation across levels for one model.

Usage:
    python scripts/evaluate.py --label mymodel --n-per-level 10
"""

import argparse
import csv
import os
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app import checker
from app.llm import LLMError, generate_story

LEVELS = [1, 2, 3, 4, 5]

FIELDS = [
    "level",
    "topic",
    "first_try_ok",
    "final_ok",
    "attempts",
    "first_in_list_rate",
    "final_in_list_rate",
    "prompt_tokens",
    "seconds",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate word-by-word story generation.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-key-env", default="LLM_API_KEY")
    parser.add_argument("--prompt-style", default=None)
    parser.add_argument("--n-per-level", type=int, default=10)
    return parser.parse_args()


def eval_topics() -> list[str]:
    topics_file = ROOT / "data" / "topics.txt"
    lines = [line.strip() for line in topics_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    return lines[-4:]


def main() -> int:
    args = parse_args()
    api_key = os.getenv(args.api_key_env)
    style = args.prompt_style or os.getenv("PROMPT_STYLE") or "full"
    model = args.model or os.getenv("LLM_MODEL") or "unset"
    topics = eval_topics()
    rng = random.Random(7)

    plan = []
    for level in LEVELS:
        for _ in range(args.n_per_level):
            plan.append((level, topics[rng.randrange(len(topics))]))

    print(f"Evaluating {len(plan)} stories (model={model}, style={style})")
    print(f"Topics: {', '.join(topics)}")

    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    csv_path = results_dir / f"eval_{args.label}.csv"

    rows = []
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for i, (level, topic) in enumerate(plan, 1):
            start = time.perf_counter()
            row = {field: "" for field in FIELDS}
            row["level"] = level
            row["topic"] = topic
            try:
                result = generate_story(
                    level,
                    "Asha",
                    "Moti",
                    [],
                    topic,
                    6,
                    base_url=args.base_url,
                    model=args.model,
                    api_key=api_key,
                    prompt_style=args.prompt_style,
                )
                row["first_try_ok"] = int(result["first_try_ok"])
                row["final_ok"] = int(result["ok"])
                row["attempts"] = result["attempts"]
                first_report = checker.check(result["first_draft"], level, {"asha", "moti"})
                row["first_in_list_rate"] = first_report["in_list_rate"]
                row["final_in_list_rate"] = result["report"]["in_list_rate"]
                row["prompt_tokens"] = result["prompt_tokens"]
            except LLMError as exc:
                print(f"[{i}/{len(plan)}] level {level} FAILED: {exc}")
                row["first_try_ok"] = 0
                row["final_ok"] = 0
                row["attempts"] = 0
                row["first_in_list_rate"] = 0.0
                row["final_in_list_rate"] = 0.0
                row["prompt_tokens"] = 0
            row["seconds"] = round(time.perf_counter() - start, 1)
            writer.writerow(row)
            rows.append(row)
            print(
                f"[{i}/{len(plan)}] level {level} ok={row['final_ok']} "
                f"first_try={row['first_try_ok']} attempts={row['attempts']} "
                f"{row['seconds']}s"
            )

    plot(rows, str(results_dir / f"eval_{args.label}.png"), args.label)
    print_summary(rows, args.label, model, style)
    print(f"\nSaved: {csv_path}")
    print(f"Saved: {results_dir / f'eval_{args.label}.png'}")
    return 0


def pct(rows: list[dict], key: str, level: int) -> float:
    subset = [row for row in rows if row["level"] == level]
    if not subset:
        return 0.0
    return 100.0 * sum(1 for row in subset if row[key] in (1, True, "1", "True")) / len(subset)


def plot(rows: list[dict], out_path: str, label: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    first = [pct(rows, "first_try_ok", level) for level in LEVELS]
    final = [pct(rows, "final_ok", level) for level in LEVELS]

    x = range(len(LEVELS))
    width = 0.38
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([i - width / 2 for i in x], first, width, label="First try", color="#e8843c")
    ax.bar([i + width / 2 for i in x], final, width, label="After checker + rewrite", color="#3f9d63")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"Level {level}" for level in LEVELS])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Pass %")
    ax.set_title(f"word-by-word eval: {label}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)


def print_summary(rows: list[dict], label: str, model: str, style: str) -> None:
    print(f"\nSummary for {label} (model={model}, style={style})")
    header = f"{'Level':<6}{'Stories':<9}{'First try':<11}{'Final':<8}{'Avg tries':<10}{'In-list (1st > final)':<24}{'Avg secs':<9}"
    print(header)
    print("-" * len(header))
    for level in LEVELS:
        subset = [row for row in rows if row["level"] == level]
        if not subset:
            continue
        attempts = [row["attempts"] for row in subset if row["attempts"] not in ("", None)]
        avg_attempts = statistics.mean(attempts) if attempts else 0.0
        avg_secs = statistics.mean([row["seconds"] for row in subset if row["seconds"] not in ("", None)])
        first_rate = statistics.mean(
            [float(row["first_in_list_rate"]) for row in subset if row["first_in_list_rate"] not in ("", None)]
        )
        final_rate = statistics.mean(
            [float(row["final_in_list_rate"]) for row in subset if row["final_in_list_rate"] not in ("", None)]
        )
        print(
            f"{level:<6}{len(subset):<9}{pct(rows, 'first_try_ok', level):<11.0f}"
            f"{pct(rows, 'final_ok', level):<8.0f}{avg_attempts:<10.1f}"
            f"{first_rate:.3f} > {final_rate:.3f}{'':<10}{avg_secs:<9.1f}"
        )


if __name__ == "__main__":
    sys.exit(main())
