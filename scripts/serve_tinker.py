"""Serve a Tinker checkpoint behind an OpenAI-compatible /chat/completions API.

Lets scripts/evaluate.py (and the app) talk to a fine-tuned model:

    python scripts/train_tinker.py            # saves results/tinker_checkpoints/latest.json
    uvicorn scripts.serve_tinker:app --port 8010
    python scripts/evaluate.py --label tinker-short --n-per-level 4 \
        --base-url http://127.0.0.1:8010/v1 \
        --model qwen35-4b-wordbyword \
        --api-key-env TINKER_API_KEY \
        --prompt-style short

Requires: pip install tinker transformers fastapi uvicorn
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import tinker
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DEFAULT_CHECKPOINT_FILE = ROOT / "results" / "tinker_checkpoints" / "latest.json"
BASE_MODEL = os.getenv("TINKER_BASE_MODEL", "Qwen/Qwen3.5-4B")

app = FastAPI(title="tinker-openai-adapter")
_state: dict = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve a Tinker checkpoint (OpenAI-compatible).")
    parser.add_argument("--checkpoint", default=None, help="tinker:// path; defaults to latest.json")
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--port", type=int, default=8010)
    return parser.parse_args()


def _resolve_checkpoint(explicit: str | None) -> str | None:
    if explicit:
        if explicit.lower() in ("none", "base"):
            return None
        return explicit
    if DEFAULT_CHECKPOINT_FILE.is_file():
        data = json.loads(DEFAULT_CHECKPOINT_FILE.read_text())
        if data.get("checkpoint"):
            return str(data["checkpoint"])
    return None


def init_state(args: argparse.Namespace) -> None:
    if _state:
        return
    from transformers import AutoTokenizer

    api_key = os.environ.get("TINKER_API_KEY", "")
    if not api_key or api_key == "your-tinker-key":
        raise RuntimeError("Set a real TINKER_API_KEY in .env first.")

    model_path = _resolve_checkpoint(args.checkpoint)
    # The SDK needs the bare service root; strip the /oai/api/v1 suffix if set.
    sdk_base = os.environ.get("TINKER_BASE_URL", "")
    if sdk_base.rstrip("/").endswith("/oai/api/v1"):
        sdk_base = sdk_base.rstrip("/")[: -len("/oai/api/v1")]
    service_client = tinker.ServiceClient(api_key=api_key, base_url=sdk_base)
    if model_path:
        print(f"Loading checkpoint: {model_path} (base: {args.base_model})")
        sampling_client = service_client.create_sampling_client(model_path=model_path)
        _state["model_name"] = f"tinker:{model_path}"
    else:
        print(f"No checkpoint; serving the BASE model {args.base_model}")
        sampling_client = service_client.create_sampling_client(base_model=args.base_model)
        _state["model_name"] = f"tinker-base:{args.base_model}"
    _state["tokenizer"] = AutoTokenizer.from_pretrained(args.base_model)
    _state["sampling_client"] = sampling_client


@app.get("/health")
def health() -> dict:
    return {"ok": True, "loaded": bool(_state)}


@app.post("/chat/completions")
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages") or []
    temperature = float(body.get("temperature", 0.7))
    max_tokens = int(body.get("max_tokens") or 1000)
    model_name = body.get("model") or _state.get("model_name", "tinker")

    try:
        init_state(parse_args())
    except RuntimeError as exc:
        return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})

    tokenizer = _state["tokenizer"]
    sampling_client = _state["sampling_client"]

    prompt_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)

    start = time.perf_counter()
    params = tinker.types.SamplingParams(max_tokens=max_tokens, temperature=temperature)
    prompt = tinker.types.ModelInput.from_ints(prompt_ids)
    try:
        call = getattr(sampling_client, "sample_async", None)
        if call is None:
            call = sampling_client.sample
        out = call(prompt=prompt, sampling_params=params, num_samples=1)
        response = out.result() if hasattr(out, "result") else out
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": {"message": f"Tinker sampling failed: {exc}"}})

    seq = response.sequences[0]
    completion_ids = list(seq.tokens)
    text = tokenizer.decode(completion_ids, skip_special_tokens=True)

    return {
        "id": "tinker-adapter",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(prompt_ids),
            "completion_tokens": len(completion_ids),
            "total_tokens": len(prompt_ids) + len(completion_ids),
        },
        "elapsed_ms": round((time.perf_counter() - start) * 1000),
    }


if __name__ == "__main__":
    import uvicorn

    args = parse_args()
    init_state(args)
    uvicorn.run(app, host="127.0.0.1", port=args.port)