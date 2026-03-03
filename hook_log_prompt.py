"""UserPromptSubmit hook — write the incoming prompt to Chroma memory.

Called by Claude Code on every user prompt submit.
Never blocks the prompt (always exits 0).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from chroma_memory import upsert_payload  # noqa: E402


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, EOFError):
        return 0

    prompt = (event.get("prompt") or "").strip()
    session_id = (event.get("session_id") or "hook-session").strip()

    if not prompt:
        return 0

    now = datetime.now(timezone.utc)
    payload = {
        "timestamp": now.isoformat(),
        "session_id": session_id,
        "turn_id": f"prompt-{now.strftime('%Y%m%dT%H%M%SZ')}",
        "source_type": "prompt",
        "user_request": prompt,
        "summary": "",
        "outcome": "",
    }

    try:
        upsert_payload(payload)
    except Exception:
        pass  # Never block the prompt on a memory write failure

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
