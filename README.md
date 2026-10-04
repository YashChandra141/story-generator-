# word-by-word

A FastAPI web app that writes short reading-practice stories for **one child** (age 5-10)
using **only words that child can already read**.

You pick the child's reading level (or use the in-app placement check), and the app asks any
OpenAI-compatible model for a story, then verifies every word against that level's word list.
Words that are too hard or sentences that are too long are sent back to the model for a rewrite
(up to 3 tries). The child never sees a word the checker did not approve without a warning.

## How it works

- **Levels** (`app/levels.py`) - cumulative word lists built from `data/levels/*.txt`
  (pre-primer, primer, grade 1-3, Dolch nouns, everyday words), plus the top 1500 English
  words from `wordfreq` at level 5. Each level also has a max sentence length (6-14 words).
- **Checker** (`app/checker.py`) - pure Python, no model. Normalizes curly apostrophes,
  tokenizes, splits sentences, and reports bad words / long sentences / in-list rate.
  Simple inflections (plural, -ed, -ing, -er, doubled consonants, dropped e) are allowed
  from level 2. Possessive `'s` is allowed at every level.
- **LLM** (`app/llm.py`) - prompts use the literal words CHILD and PET, so real names never
  reach the model; names are swapped in afterwards. If the checker fails the draft, the draft
  plus a rewrite message are sent back at a lower temperature (max 3 rewrites). Thinking
  blocks are stripped from model output. Reading-comprehension questions are generated the
  same way and checked too.
- **UI** (`app/static/index.html`) - one vanilla HTML/CSS/JS page with a placement check,
  story writing, clickable words, stuck-word tracking, questions, and a print view.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env            # then edit .env with your model settings
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

### Configuration (`.env`)

| Key             | Meaning                                        |
| --------------- | ---------------------------------------------- |
| `LLM_BASE_URL`  | OpenAI-compatible API base URL                 |
| `LLM_MODEL`     | Model name                                     |
| `LLM_API_KEY`   | API key (never logged, never sent to the user) |
| `PROMPT_STYLE`  | `full` (default) or `short`                    |

## Word lists

`data/levels/` ships empty. Fill the files (one word per line, whitespace separated, lowercase):

`preprimer.txt`, `primer.txt`, `grade1.txt`, `grade2.txt`, `grade3.txt`, `nouns.txt`, `everyday.txt`

## Tests

```bash
pytest
```

Word-list count tests fail until the real word lists are added.

## Evaluation

Runs the last 4 topics in `data/topics.txt` across all 5 levels, saves a CSV and a grouped
bar chart, and prints a summary table:

```bash
python scripts/evaluate.py --label mymodel --n-per-level 10
# optional: --base-url, --model, --api-key-env (default LLM_API_KEY), --prompt-style
```

Results land in `results/eval_<label>.csv` and `results/eval_<label>.png`.

## Deploy to Render

The included `render.yaml` defines one Python web service (build: `pip install -r requirements.txt`,
start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check `/health`).

1. Push this repo to GitHub/GitLab.
2. In Render: **New + > Blueprint**, pick the repo.
3. Set the env vars `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, and `PROMPT_STYLE` when prompted.

No database, no login, no extra frameworks.
