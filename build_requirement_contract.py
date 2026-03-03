from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from chroma_memory import DEFAULT_DB_PATH, flatten_query_results, get_default_collection_name, query_memory


DEFAULT_AUTHORITY_TOKENS = [
    "requirements",
    "confluence",
    "jira",
]
DEFAULT_AUTHORITY_TYPES = {
    "knowledge",
    "confluence",
    "jira",
}
DEFAULT_PRIORITY_HINTS = [
    "must",
    "required",
    "high priority",
    "approval",
    "import",
    "export",
    "csv",
    "excel",
    "pdf",
]
LIST_MARKER = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
HTML_TAG = re.compile(r"<[^>]+>")


def write_stdout(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.buffer.write(text.encode(encoding, errors="replace"))


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split()).strip()


def record_source_text(record: dict) -> str:
    payload = record.get("payload") or {}
    metadata = record.get("metadata") or {}
    parts = [
        str(payload.get("source_type") or metadata.get("source_type") or ""),
        str(payload.get("source_name") or metadata.get("source_name") or ""),
        " ".join(str(item) for item in payload.get("knowledge_sources") or []),
    ]
    return " ".join(part for part in parts if part).lower()


def is_authoritative(record: dict, authority_tokens: list[str]) -> bool:
    payload = record.get("payload") or {}
    metadata = record.get("metadata") or {}
    source_type = str(payload.get("source_type") or metadata.get("source_type") or "").lower()
    if source_type in DEFAULT_AUTHORITY_TYPES:
        return True

    source_text = record_source_text(record)
    if not any(token.lower() in source_text for token in authority_tokens):
        return False

    return source_type == "knowledge"


def clean_requirement_line(line: str) -> str:
    cleaned = HTML_TAG.sub(" ", line)
    cleaned = normalize_whitespace(LIST_MARKER.sub("", cleaned))
    prefixes = (
        "user request:",
        "summary:",
        "files changed:",
        "decisions:",
        "outcome:",
        "confluence page import:",
        "imported confluence page",
        "reference knowledge import:",
        "indexed knowledge section",
        "jira issue import:",
        "imported jira issue",
    )
    lowered = cleaned.lower()
    if lowered.startswith(prefixes):
        return ""
    return cleaned


def split_requirement_fragments(line: str) -> list[str]:
    if " - " not in line:
        return [line]

    fragments = [normalize_whitespace(part) for part in line.split(" - ")]
    filtered = [part for part in fragments if len(part) >= 12]
    return filtered or [line]


def extract_requirement_lines(record: dict, priority_hints: list[str]) -> list[str]:
    payload = record.get("payload") or {}
    text_parts = [
        record.get("document") or "",
        str(payload.get("summary") or ""),
        str(payload.get("user_request") or ""),
        str(payload.get("outcome") or ""),
    ]
    text = "\n".join(part for part in text_parts if part)

    candidates: list[str] = []
    for raw_line in text.splitlines():
        line = normalize_whitespace(raw_line)
        lowered = line.lower()
        if not line:
            continue
        if LIST_MARKER.match(raw_line) or any(hint in lowered for hint in priority_hints):
            cleaned = clean_requirement_line(line)
            if cleaned:
                candidates.extend(split_requirement_fragments(cleaned))

    return candidates


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def build_contract(records: list[dict], query: str, authority_tokens: list[str], priority_hints: list[str]) -> dict:
    authoritative = [record for record in records if is_authoritative(record, authority_tokens)]
    supporting = [record for record in records if record not in authoritative]

    requirements: list[str] = []
    constraints: list[str] = []
    open_questions: list[str] = []

    for record in authoritative:
        requirements.extend(extract_requirement_lines(record, priority_hints))
        payload = record.get("payload") or {}
        constraints.extend(str(item) for item in payload.get("constraints") or [])
        open_questions.extend(str(item) for item in payload.get("open_questions") or [])

    requirements = dedupe_preserving_order(requirements)
    constraints = dedupe_preserving_order([normalize_whitespace(item) for item in constraints if normalize_whitespace(item)])
    open_questions = dedupe_preserving_order([normalize_whitespace(item) for item in open_questions if normalize_whitespace(item)])

    coverage = [{"requirement": item, "status": "unaddressed"} for item in requirements]
    evidence = []
    for record in authoritative:
        payload = record.get("payload") or {}
        metadata = record.get("metadata") or {}
        evidence.append(
            {
                "id": record.get("id"),
                "source_type": payload.get("source_type") or metadata.get("source_type") or "",
                "source_name": payload.get("source_name") or metadata.get("source_name") or "",
                "knowledge_sources": payload.get("knowledge_sources") or [],
                "summary": payload.get("summary") or metadata.get("summary") or "",
            }
        )

    return {
        "query": query,
        "authoritative_hit_count": len(authoritative),
        "supporting_hit_count": len(supporting),
        "requirements": requirements,
        "constraints": constraints,
        "open_questions": open_questions,
        "coverage": coverage,
        "evidence": evidence,
    }


def format_contract(contract: dict) -> str:
    lines = [f"Requirement contract for query: {contract['query']}"]
    lines.append(f"Authoritative hits: {contract['authoritative_hit_count']}")
    lines.append(f"Supporting hits: {contract['supporting_hit_count']}")

    requirements = contract.get("requirements") or []
    if requirements:
        lines.append("Requirements:")
        for index, item in enumerate(requirements, start=1):
            lines.append(f"  {index}. {item}")
    else:
        lines.append("Requirements: none extracted")

    constraints = contract.get("constraints") or []
    if constraints:
        lines.append("Constraints:")
        for item in constraints:
            lines.append(f"  - {item}")

    open_questions = contract.get("open_questions") or []
    if open_questions:
        lines.append("Open questions:")
        for item in open_questions:
            lines.append(f"  - {item}")

    evidence = contract.get("evidence") or []
    if evidence:
        lines.append("Evidence:")
        for item in evidence[:5]:
            source_type = item.get("source_type") or "unknown"
            source_name = item.get("source_name") or "unknown"
            lines.append(f"  - {item.get('id')}: {source_type} / {source_name}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a requirement contract from Chroma memory so planning can prove requirement coverage."
    )
    parser.add_argument("--query", required=True, help="Task-specific query.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Persistent Chroma database path.")
    parser.add_argument("--collection", default=get_default_collection_name(), help="Chroma collection name.")
    parser.add_argument("--limit", type=int, default=12, help="Maximum number of memory hits to inspect.")
    parser.add_argument(
        "--authority-token",
        action="append",
        help="Source token treated as authoritative. Defaults to requirements, confluence, jira.",
    )
    parser.add_argument(
        "--priority-hint",
        action="append",
        help="Substring hint that causes a line to be treated as a likely requirement.",
    )
    parser.add_argument("--allow-empty", action="store_true", help="Exit successfully even if no authoritative hits exist.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text report.")
    args = parser.parse_args()

    result = query_memory(
        query=args.query,
        db_path=Path(args.db_path),
        collection_name=args.collection,
        limit=max(args.limit, 1),
    )
    records = flatten_query_results(result)
    authority_tokens = args.authority_token or DEFAULT_AUTHORITY_TOKENS
    priority_hints = args.priority_hint or DEFAULT_PRIORITY_HINTS
    contract = build_contract(records, args.query, authority_tokens, priority_hints)

    if contract["authoritative_hit_count"] == 0 and not args.allow_empty:
        sys.stderr.write(
            "No authoritative requirement hits were found. Refusing to continue without a requirement contract.\n"
        )
        if args.json:
            json.dump(contract, sys.stderr, indent=2)
            sys.stderr.write("\n")
        else:
            write_stdout(format_contract(contract) + "\n")
        return 2

    if args.json:
        json.dump(contract, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        write_stdout(format_contract(contract) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
