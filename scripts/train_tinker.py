"""Fine-tune Qwen3.5-4B on data/train.jsonl with Tinker (LoRA rank 32).

Pattern (per https://tinker.dev/docs):
    - base model: Qwen/Qwen3.5-4B
    - LoRA rank: 32, supervised cross-entropy on the assistant tokens only
    - data: data/train.jsonl in OpenAI messages format (FromConversationFileBuilder
      equivalent, implemented inline so a bare `pip install tinker` is enough)

Requires:
    pip install tinker transformers
    set TINKER_API_KEY in .env (never commit it)

After training, serve the checkpoint (e.g. with vLLM or Tinker's sampling API)
and evaluate it against the app with:

    python scripts/evaluate.py --label tinker-short --n-per-level 4 --prompt-style short

Usage:
    python scripts/train_tinker.py                 # train 1 epoch
    python scripts/train_tinker.py --epochs 2      # more epochs if loss still falling
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

TRAIN_PATH = ROOT / "data" / "train.jsonl"

BASE_MODEL = "Qwen/Qwen3.5-4B"
LORA_RANK = 32
LR = 1e-4
BATCH_SIZE = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune with Tinker LoRA.")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--lr", type=float, default=LR)
    parser.add_argument("--rank", type=int, default=LORA_RANK)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--save-dir", default="results/tinker_checkpoints")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    api_key = os.environ.get("TINKER_API_KEY", "")
    if not api_key or api_key == "your-tinker-key":
        print("Set a real TINKER_API_KEY in .env first.")
        sys.exit(1)

    if not TRAIN_PATH.is_file() or TRAIN_PATH.stat().st_size == 0:
        print(f"{TRAIN_PATH} is missing or empty. Run: python scripts/generate_dataset.py --target 100")
        sys.exit(1)

    import tinker
    from tinker import ServiceClient

    # The SDK needs the bare service root; the OAI serving URL in .env has an
    # extra /oai/api/v1 suffix that the training API does not use.
    sdk_base = os.environ.get("TINKER_BASE_URL", "")
    if sdk_base.rstrip("/").endswith("/oai/api/v1"):
        sdk_base = sdk_base.rstrip("/")[: -len("/oai/api/v1")]
    sc = ServiceClient(api_key=api_key, base_url=sdk_base)  # "" -> SDK default
    training_client = sc.create_lora_training_client(base_model=BASE_MODEL, rank=args.rank)

    # --- data -------------------------------------------------------------
    # Tokenize data/train.jsonl (OpenAI messages format) into Datums with
    # weights only on the assistant completion (supervised fine-tune).
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    conversations = [
        json.loads(line)["messages"]
        for line in TRAIN_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Loaded {len(conversations)} conversations from {TRAIN_PATH}")

    def make_datum(messages: list[dict]) -> tinker.Datum:
        # Split at the TEXT level (the renders are exact string prefixes), then
        # tokenize each part — token-level prefix stripping is unreliable here
        # because newline BPE merges differ across the prompt/completion boundary.
        full_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        prompt_text = tokenizer.apply_chat_template(
            messages[:-1], tokenize=False, add_generation_prompt=True
        )
        if not full_text.startswith(prompt_text):
            raise RuntimeError("chat template renders are not prefix-consistent")
        completion_text = full_text[len(prompt_text):]
        prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
        completion_ids = tokenizer(completion_text, add_special_tokens=False)["input_ids"]
        input_tokens = prompt_ids + completion_ids
        target_tokens = input_tokens[1:]
        weights = [0.0] * (len(prompt_ids) - 1) + [1.0] * len(completion_ids)
        return tinker.Datum(
            model_input=tinker.ModelInput.from_ints(input_tokens[:-1]),
            loss_fn_inputs={
                "weights": tinker.TensorData(data=weights, dtype="float32", shape=[len(weights)]),
                "target_tokens": tinker.TensorData(
                    data=target_tokens, dtype="int64", shape=[len(target_tokens)]
                ),
            },
        )

    conversations = [c for c in conversations if (c[-1].get("content") or "").strip()]
    batches = [
        [make_datum(m) for m in conversations[i : i + args.batch_size]]
        for i in range(0, len(conversations), args.batch_size)
    ]
    print(f"{len(batches)} batches of up to {args.batch_size}")

    for epoch in range(args.epochs):
        step = 0
        for batch in batches:
            fb = training_client.forward_backward(data=batch, loss_fn="cross_entropy")
            os_step = training_client.optim_step(
                tinker.types.AdamParams(
                    learning_rate=args.lr, beta1=0.9, beta2=0.95, eps=1e-8
                )
            )
            fb.result()
            os_step.result()
            step += 1
            print(f"epoch {epoch + 1} step {step}: {len(batch)} examples", flush=True)
        print(f"epoch {epoch + 1} done")

    # --- save checkpoint --------------------------------------------------
    save_dir = ROOT / args.save_dir
    save_dir.mkdir(parents=True, exist_ok=True)
    path_future = training_client.save_weights_for_sampler(name="word-by-word-qwen35-4b")
    checkpoint = path_future.result() if hasattr(path_future, "result") else path_future
    path = getattr(checkpoint, "path", None) or str(checkpoint)
    (save_dir / "latest.json").write_text(json.dumps({"checkpoint": path}))
    print(f"Checkpoint saved: {path}")
    print("Next: serve it and run scripts/evaluate.py --prompt-style short to compare.")


if __name__ == "__main__":
    main()