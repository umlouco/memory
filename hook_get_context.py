"""UserPromptSubmit hook — query Chroma memory and inject relevant context.

Called by GitHub Copilot Chat on every user prompt submit.
Outputs a <memory_context> block to stdout, which Copilot injects
into the conversation before the model processes the prompt.
Never blocks the prompt (always exits 0).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from chroma_memory import flatten_query_results, query_memory  # noqa: E402


def format_context(records: list[dict], query: str) -> str:
    if not records:
        return ""

    lines = ["<memory_context>", f"Relevant prior context for: {query}"]
    for i, record in enumerate(records, 1):
        payload = record.get("payload") or {}
        metadata = record.get("metadata") or {}
        user_req = (payload.get("user_request") or metadata.get("user_request", "")).strip()
        summary = (payload.get("summary") or metadata.get("summary", "")).strip()
        outcome = (payload.get("outcome") or metadata.get("outcome", "")).strip()
        if user_req or summary:
            lines.append(f"{i}. request: {user_req}")
            if summary:
                lines.append(f"   summary: {summary}")
            if outcome:
                lines.append(f"   outcome: {outcome}")
    lines.append("</memory_context>")
    return "\n".join(lines)


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, EOFError):
        return 0

    prompt = (event.get("prompt") or "").strip()
    if not prompt:
        return 0

    try:
        result = query_memory(query=prompt, limit=3)
        records = flatten_query_results(result)
        context = format_context(records, prompt)
        if context:
            encoding = sys.stdout.encoding or "utf-8"
            sys.stdout.buffer.write(context.encode(encoding, errors="replace"))
            sys.stdout.buffer.write(b"\n")
    except Exception:
        pass  # Never block the prompt on a memory read failure

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
