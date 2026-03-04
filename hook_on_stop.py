"""Stop hook — persist the full context window into Chroma when a turn ends.

Called by VS Code Copilot on the ``stop`` event (agent finishes responding).
Captures assistant responses, file references, tool calls, and the complete
conversation so that future recall queries can surface what actually happened
during a turn — not just the initial prompt.

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_messages(event: dict) -> list[dict]:
    """Return the chat messages array from the event, tolerating different shapes."""
    messages = event.get("chatMessages") or event.get("messages") or []
    if isinstance(messages, list):
        return messages
    return []


def _build_transcript(messages: list[dict]) -> str:
    """Concatenate messages into a plain-text transcript."""
    lines: list[str] = []
    for msg in messages:
        role = (msg.get("role") or "unknown").capitalize()
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:2000]}")
    return "\n".join(lines)


def _extract_user_request(messages: list[dict]) -> str:
    """Pull the last user message as the canonical user request."""
    for msg in reversed(messages):
        if (msg.get("role") or "").lower() in ("user", "human"):
            content = (msg.get("content") or "").strip()
            if content:
                return content[:1200]
    return ""


def _extract_assistant_response(messages: list[dict]) -> str:
    """Pull the last assistant message as the outcome/response."""
    for msg in reversed(messages):
        if (msg.get("role") or "").lower() in ("assistant", "model"):
            content = (msg.get("content") or "").strip()
            if content:
                return content[:2000]
    return ""


def _extract_files(event: dict, messages: list[dict]) -> tuple[list[str], list[str]]:
    """Best-effort extraction of files read and files changed."""
    files_read: list[str] = []
    files_changed: list[str] = []

    # Top-level fields some hook payloads provide
    for key in ("filesRead", "files_read", "references"):
        for item in (event.get(key) or []):
            path = item if isinstance(item, str) else (item.get("path") or item.get("uri") or "")
            if path:
                files_read.append(str(path))

    for key in ("filesChanged", "files_changed", "edits"):
        for item in (event.get(key) or []):
            path = item if isinstance(item, str) else (item.get("path") or item.get("uri") or "")
            if path:
                files_changed.append(str(path))

    # Scan tool-call results inside messages for file paths
    for msg in messages:
        tool_calls = msg.get("tool_calls") or msg.get("toolCalls") or []
        for tc in tool_calls:
            fn = tc.get("function") or tc.get("name") or {}
            name = fn.get("name") or tc.get("name") or ""
            args_raw = fn.get("arguments") or tc.get("arguments") or ""
            if isinstance(args_raw, str):
                try:
                    args_obj = json.loads(args_raw)
                except (json.JSONDecodeError, ValueError):
                    args_obj = {}
            else:
                args_obj = args_raw if isinstance(args_raw, dict) else {}

            path = args_obj.get("filePath") or args_obj.get("path") or args_obj.get("file") or ""
            if path:
                if name in ("read_file", "semantic_search", "grep_search", "file_search"):
                    files_read.append(str(path))
                elif name in ("create_file", "replace_string_in_file", "multi_replace_string_in_file",
                              "edit_notebook_file"):
                    files_changed.append(str(path))

    return list(dict.fromkeys(files_read)), list(dict.fromkeys(files_changed))


def _extract_decisions(messages: list[dict]) -> list[str]:
    """Extract tool call names as lightweight decisions."""
    decisions: list[str] = []
    for msg in messages:
        tool_calls = msg.get("tool_calls") or msg.get("toolCalls") or []
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name") or ""
            if name:
                decisions.append(f"tool:{name}")
    return list(dict.fromkeys(decisions))[:20]


def _collapse(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit - 3].rstrip() + "..." if len(collapsed) > limit else collapsed


def _build_summary(user_request: str, assistant_response: str, messages: list[dict]) -> str:
    turn_count = len(messages)
    resp_preview = _collapse(assistant_response, 300) if assistant_response else "no response captured"
    return _collapse(
        f"Turn with {turn_count} messages. Request: {user_request} | Response preview: {resp_preview}",
        500,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, EOFError):
        return 0

    messages = _extract_messages(event)
    user_request = _extract_user_request(messages)
    assistant_response = _extract_assistant_response(messages)

    # Nothing meaningful to persist
    if not user_request and not assistant_response and not messages:
        return 0

    session_id = (event.get("session_id") or event.get("sessionId") or "hook-session").strip()
    now = datetime.now(timezone.utc)
    transcript = _build_transcript(messages)
    files_read, files_changed = _extract_files(event, messages)
    decisions = _extract_decisions(messages)

    payload = {
        "timestamp": now.isoformat(),
        "session_id": session_id,
        "turn_id": f"stop-{now.strftime('%Y%m%dT%H%M%SZ')}",
        "source_type": "stop",
        "source_name": "copilot-stop",
        "user_request": user_request or "(no user message captured)",
        "summary": _build_summary(user_request, assistant_response, messages),
        "outcome": _collapse(assistant_response, 500) if assistant_response else "turn ended",
        "constraints": [],
        "files_read": files_read,
        "files_changed": files_changed,
        "knowledge_sources": [],
        "decisions": decisions,
        "open_questions": [],
    }

    # Persist raw transcript alongside payload for deeper recall
    _save_transcript(now, session_id, transcript)

    try:
        upsert_payload(payload)
    except Exception:
        pass  # Never block

    return 0


def _save_transcript(now: datetime, session_id: str, transcript: str) -> None:
    """Write the raw transcript to disk so it can be referenced later."""
    if not transcript.strip():
        return
    try:
        out_dir = _THIS_DIR / "storage" / "app" / "memory-transcripts"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{session_id}_stop.txt"
        (out_dir / filename).write_text(transcript, encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
