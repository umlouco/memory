from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from chroma_memory import DEFAULT_DB_PATH, flatten_query_results, get_default_collection_name, query_memory


def write_stdout(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.buffer.write(text.encode(encoding, errors="replace"))


def format_brief(records: list[dict], query: str) -> str:
    if not records:
        return f"Memory brief for query: {query}\nNo matching prior memory found."

    lines = [f"Memory brief for query: {query}"]
    for index, record in enumerate(records, start=1):
        payload = record.get("payload") or {}
        lines.append(f"{index}. {record['id']}")
        lines.append(f"   user_request: {payload.get('user_request') or record['metadata'].get('user_request', '')}")
        lines.append(f"   summary: {payload.get('summary') or record['metadata'].get('summary', '')}")
        lines.append(f"   outcome: {payload.get('outcome') or record['metadata'].get('outcome', '')}")

        decisions = payload.get("decisions") or []
        if decisions:
            lines.append(f"   decisions: {'; '.join(decisions[:3])}")

        files_changed = payload.get("files_changed") or []
        if files_changed:
            lines.append(f"   files_changed: {', '.join(files_changed[:5])}")

        knowledge_sources = payload.get("knowledge_sources") or []
        if knowledge_sources:
            lines.append(f"   knowledge_sources: {', '.join(knowledge_sources[:5])}")

        source_type = payload.get("source_type") or record["metadata"].get("source_type", "")
        source_name = payload.get("source_name") or record["metadata"].get("source_name", "")
        if source_type or source_name:
            lines.append(f"   source: {source_type or 'unknown'} / {source_name or 'unknown'}")

    return "\n".join(lines)


def filter_records(records: list[dict], sources: list[str], source_types: list[str]) -> list[dict]:
    if not sources and not source_types:
        return records

    normalized_sources = [value.lower() for value in sources]
    normalized_types = [value.lower() for value in source_types]
    filtered: list[dict] = []

    for record in records:
        payload = record.get("payload") or {}
        metadata = record.get("metadata") or {}
        source_name = str(payload.get("source_name") or metadata.get("source_name") or "").lower()
        source_type = str(payload.get("source_type") or metadata.get("source_type") or "").lower()

        source_match = not normalized_sources or any(
            token in source_name for token in normalized_sources
        )
        type_match = not normalized_types or source_type in normalized_types

        if source_match and type_match:
            filtered.append(record)

    return filtered


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def filter_by_session_and_date(
    records: list[dict],
    session_prefix: str | None,
    date_from: str | None,
    date_to: str | None,
) -> list[dict]:
    from_dt = parse_timestamp(f"{date_from}T00:00:00+00:00") if date_from else None
    to_dt = parse_timestamp(f"{date_to}T23:59:59+00:00") if date_to else None
    normalized_prefix = (session_prefix or "").lower()

    filtered: list[dict] = []
    for record in records:
        payload = record.get("payload") or {}
        metadata = record.get("metadata") or {}
        session_id = str(payload.get("session_id") or metadata.get("session_id") or "")
        timestamp = str(payload.get("timestamp") or metadata.get("timestamp") or "")
        parsed = parse_timestamp(timestamp)

        if normalized_prefix and not session_id.lower().startswith(normalized_prefix):
            continue
        if from_dt and (parsed is None or parsed < from_dt):
            continue
        if to_dt and (parsed is None or parsed > to_dt):
            continue

        filtered.append(record)

    return filtered


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall and summarize prior Chroma memory for the next turn.")
    parser.add_argument("--query", required=True, help="Natural language query.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Persistent Chroma database path.")
    parser.add_argument("--collection", default=get_default_collection_name(), help="Chroma collection name.")
    parser.add_argument("--limit", type=int, default=3, help="Maximum number of records to summarize.")
    parser.add_argument("--session", help="Optional session identifier filter.")
    parser.add_argument("--session-prefix", help="Filter results to session ids that start with this value.")
    parser.add_argument("--date-from", help="Filter results from this UTC date onward in YYYY-MM-DD format.")
    parser.add_argument("--date-to", help="Filter results through this UTC date in YYYY-MM-DD format.")
    parser.add_argument("--source", action="append", help="Filter results by source name or path substring.")
    parser.add_argument("--source-type", action="append", help="Filter results by source type such as knowledge or transcript.")
    parser.add_argument("--json", action="store_true", help="Emit raw flattened JSON instead of a text brief.")
    args = parser.parse_args()

    result = query_memory(
        query=args.query,
        db_path=Path(args.db_path),
        collection_name=args.collection,
        limit=200 if (args.source or args.source_type) else max(args.limit * 5, args.limit),
        session_id=args.session,
    )
    records = flatten_query_results(result)
    records = filter_records(records, args.source or [], args.source_type or [])
    records = filter_by_session_and_date(records, args.session_prefix, args.date_from, args.date_to)[: args.limit]
    if args.json:
        json.dump(records, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    write_stdout(format_brief(records, args.query) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
