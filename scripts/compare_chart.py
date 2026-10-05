"""Combine eval CSVs into one comparison chart.

    python scripts/compare_chart.py --label gemma-cf --label tinker-short
Outputs results/eval_compare.png with first-try and final bars per model per level.
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEVELS = [1, 2, 3, 4, 5]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine eval CSVs into one chart.")
    parser.add_argument("--label", action="append", required=True, help="eval label (repeatable)")
    parser.add_argument("--out", default="results/eval_compare.png")
    return parser.parse_args()


def pct(rows: list[dict], key: str, level: int) -> float:
    subset = [row for row in rows if int(row["level"]) == level]
    if not subset:
        return 0.0
    hits = sum(1 for row in subset if str(row[key]).strip() in ("1", "True", "true"))
    return 100.0 * hits / len(subset)


def load(label: str) -> dict[int, list[dict]]:
    path = ROOT / "results" / f"eval_{label}.csv"
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return {level: [row for row in rows if int(row["level"]) == level] for level in LEVELS}


def main() -> int:
    args = parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors_first = ["#e8843c", "#d3a02c"]
    colors_final = ["#3f9d63", "#7fb9d9"]

    x = range(len(LEVELS))
    n = len(args.label)
    width = 0.8 / (2 * n)
    fig, ax = plt.subplots(figsize=(9, 5))

    for i, label in enumerate(args.label):
        by_level = load(label)
        first = [pct(by_level[level], "first_try_ok", level) for level in LEVELS]
        final = [pct(by_level[level], "final_ok", level) for level in LEVELS]
        base = -0.4 + i * 2 * width
        ax.bar([j + base for j in x], first, width, color=colors_first[i % 2],
               label=f"{label} first try")
        ax.bar([j + base + width for j in x], final, width, color=colors_final[i % 2],
               label=f"{label} after rewrite")

    ax.set_xticks(list(x))
    ax.set_xticklabels([f"Level {lv}" for lv in LEVELS])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Pass %")
    ax.set_title("word-by-word eval: model comparison")
    ax.legend(fontsize=8)
    fig.tight_layout()

    out = ROOT / args.out
    fig.savefig(out, dpi=150)
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())