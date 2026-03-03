from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def normalize_items(values: list[str] | None) -> list[str]:
    return [value.strip() for value in (values or []) if value and value.strip()]


def git_changed_files() -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--short"],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return []

    changed: list[str] = []
    for line in completed.stdout.splitlines():
        if len(line) >= 4:
            changed.append(line[3:].strip())
    return [item for item in changed if item]


def collapse_whitespace(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def extract_user_request(transcript: str) -> str:
    candidates: list[str] = []
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if lowered.startswith("user:") or lowered.startswith("human:") or lowered.startswith("prompt:"):
            candidates.append(line.split(":", 1)[1].strip())

    if candidates:
        return collapse_whitespace(candidates[-1], 1200)
    return collapse_whitespace(transcript, 1200)


def build_summary(transcript: str, user_request: str) -> str:
    line_count = len([line for line in transcript.splitlines() if line.strip()])
    return collapse_whitespace(
        f"Captured transcript with {line_count} non-empty lines. Latest user request: {user_request}",
        500,
    )


def build_outcome() -> str:
    return "Transcript captured and memory persisted."


def read_transcript(transcript_path: str | None, read_stdin: bool) -> str:
    parts: list[str] = []
    if transcript_path:
        parts.append(Path(transcript_path).read_text(encoding="utf-8-sig"))
    if read_stdin:
        stdin_text = sys.stdin.read()
        if stdin_text.strip():
            parts.append(stdin_text)
    return "\n".join(part for part in parts if part.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Chroma memory payload for a chat turn.")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--user-request")
    parser.add_argument("--summary")
    parser.add_argument("--outcome")
    parser.add_argument("--transcript-path")
    parser.add_argument("--stdin-transcript", action="store_true")
    parser.add_argument("--constraint", action="append")
    parser.add_argument("--file-read", action="append")
    parser.add_argument("--file-changed", action="append")
    parser.add_argument("--knowledge-source", action="append")
    parser.add_argument("--decision", action="append")
    parser.add_argument("--open-question", action="append")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    transcript = read_transcript(args.transcript_path, args.stdin_transcript)
    user_request = (args.user_request or "").strip() or extract_user_request(transcript)
    if not user_request:
        raise SystemExit("A user request or transcript is required to build the payload.")

    summary = (args.summary or "").strip() or build_summary(transcript, user_request)
    outcome = (args.outcome or "").strip() or build_outcome()
    files_changed = normalize_items(args.file_changed) or git_changed_files()

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": args.session_id,
        "turn_id": args.turn_id,
        "user_request": user_request,
        "summary": summary,
        "constraints": normalize_items(args.constraint),
        "files_read": normalize_items(args.file_read),
        "files_changed": files_changed,
        "knowledge_sources": normalize_items(args.knowledge_source),
        "decisions": normalize_items(args.decision),
        "open_questions": normalize_items(args.open_question),
        "outcome": outcome,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
