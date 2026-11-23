"""Shared helpers: data loading, the Claude API call, and CSV input/output."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RUBRICS = ROOT / "rubrics"
RESULTS = ROOT / "results"

DEFAULT_MODEL = "claude-haiku-5-5"
CHECKS = ["accurate", "complete", "grounded", "concise", "actionable"]
BOOL_FIELDS = ["gate_pass", *CHECKS]


# ---------- data ----------

def load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_outputs() -> list[dict]:
    return load_jsonl(DATA / "outputs.jsonl")


def load_key() -> dict[str, dict]:
    return {row["id"]: row for row in load_jsonl(DATA / "answer_key.jsonl")}


def load_pairs() -> list[dict]:
    return load_jsonl(DATA / "pairs.jsonl")


def load_policy() -> str:
    return (DATA / "policy.md").read_text()


# ---------- Claude API ----------

def get_client():
    """Create an Anthropic client. Reads ANTHROPIC_API_KEY from the environment."""
    import anthropic

    return anthropic.Anthropic()


def call_tool(client, model: str, system: str, user: str, tool: dict,
              temperature: float | None = None, max_tokens: int = 1024) -> tuple[dict, dict]:
    """Call Claude and force it to answer through one tool.

    Forcing a tool call gives structured output: the tool's input_schema
    defines the JSON the judge must return.
    Returns (tool_input, usage).
    """
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
    )
    # Only send temperature when asked. The API default is used otherwise.
    if temperature is not None:
        kwargs["temperature"] = temperature

    start = time.perf_counter()
    response = client.messages.create(**kwargs)
    latency = time.perf_counter() - start

    block = next((b for b in response.content if b.type == "tool_use"), None)
    if block is None:
        raise ValueError("Model returned no tool call")
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "latency_s": round(latency, 2),
    }
    return block.input, usage


# ---------- CSV ----------

def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def parse_bool(value) -> bool | None:
    """Parse a CSV cell into True, False, or None (blank or unknown)."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1", "pass"}:
        return True
    if text in {"false", "f", "no", "n", "0", "fail"}:
        return False
    return None


def parse_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def usage_summary(rows: list[dict]) -> str:
    ok = [r for r in rows if not r.get("error")]
    tin = sum(int(r.get("input_tokens") or 0) for r in ok)
    tout = sum(int(r.get("output_tokens") or 0) for r in ok)
    lat = sum(float(r.get("latency_s") or 0) for r in ok)
    errors = len(rows) - len(ok)
    return (f"{len(ok)} calls, {errors} errors, input tokens {tin}, output tokens {tout}, "
            f"total API time {lat:.1f}s")
