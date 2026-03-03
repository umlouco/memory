from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chroma_memory import DEFAULT_DB_PATH, get_default_collection_name, upsert_payload


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PAYLOAD_DIR = ROOT_DIR / "storage" / "app" / "memory-payloads"
DEFAULT_TRANSCRIPT_DIR = ROOT_DIR / "storage" / "app" / "memory-transcripts"
DEFAULT_KNOWLEDGE_DIR = ROOT_DIR / ".knowledge"
DEFAULT_EXTERNAL_DIR = ROOT_DIR / "storage" / "app" / "memory-external"
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 180


def collapse_whitespace(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


def split_large_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
            tail = current[-overlap:].strip() if overlap > 0 else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            start = 0
            while start < len(paragraph):
                end = min(start + chunk_size, len(paragraph))
                piece = paragraph[start:end].strip()
                if piece:
                    chunks.append(piece)
                if end >= len(paragraph):
                    current = ""
                    break
                start = max(end - overlap, start + 1)

    if current:
        chunks.append(current)

    return chunks


def load_payloads(payload_dir: Path) -> list[dict]:
    payloads: list[dict] = []
    if not payload_dir.exists():
        return payloads

    for path in sorted(payload_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        payload.setdefault("source_type", "payload")
        payload.setdefault("source_name", path.stem)
        payloads.extend(chunk_payload_record(payload))
    return payloads


def build_payload_chunk_text(payload: dict[str, Any]) -> str:
    parts = [
        str(payload.get("user_request") or ""),
        str(payload.get("summary") or ""),
        str(payload.get("outcome") or ""),
        "\n".join(str(item) for item in payload.get("constraints") or []),
        "\n".join(str(item) for item in payload.get("decisions") or []),
        "\n".join(str(item) for item in payload.get("open_questions") or []),
        "\n".join(str(item) for item in payload.get("files_read") or []),
        "\n".join(str(item) for item in payload.get("files_changed") or []),
        "\n".join(str(item) for item in payload.get("knowledge_sources") or []),
    ]
    return "\n\n".join(part for part in parts if part.strip())


def chunk_payload_record(payload: dict[str, Any]) -> list[dict]:
    chunk_source = build_payload_chunk_text(payload)
    chunks = split_large_text(chunk_source)
    if len(chunks) <= 1:
        return [payload]

    chunked_payloads: list[dict] = []
    base_turn_id = str(payload.get("turn_id") or "payload")
    base_summary = str(payload.get("summary") or "")
    base_outcome = str(payload.get("outcome") or "")
    decisions = [str(item) for item in payload.get("decisions") or []]

    for chunk_index, chunk_body in enumerate(chunks, start=1):
        chunk_payload = dict(payload)
        chunk_payload["turn_id"] = f"{base_turn_id}-chunk-{chunk_index:03d}"
        chunk_payload["summary"] = collapse_whitespace(chunk_body, 500)
        chunk_payload["outcome"] = base_outcome or f"Indexed payload chunk {chunk_index}."
        chunk_payload["decisions"] = decisions + [f"Payload chunk {chunk_index}"]
        chunked_payloads.append(chunk_payload)

    if base_summary:
        chunked_payloads[0]["summary"] = base_summary

    return chunked_payloads


def build_knowledge_payload(
    path: Path,
    section_title: str,
    section_body: str,
    section_index: int,
    chunk_index: int,
    chunk_body: str,
) -> dict:
    relative_path = str(path.relative_to(ROOT_DIR)).replace("\\", "/")
    summary = collapse_whitespace(chunk_body, 500)
    section_slug = slugify(section_title)
    source_name = f"{path.stem}:{section_slug}"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "knowledge-import",
        "turn_id": f"{path.stem}-{section_index:03d}-{section_slug}-chunk-{chunk_index:03d}",
        "source_type": "knowledge",
        "source_name": source_name,
        "user_request": f"Reference knowledge import: {path.stem} / {section_title}",
        "summary": summary,
        "constraints": [],
        "files_read": [relative_path],
        "files_changed": [],
        "knowledge_sources": [relative_path],
        "decisions": [f"Indexed repository knowledge section: {section_title}", f"Chunk {chunk_index}"],
        "open_questions": [],
        "outcome": f"Indexed knowledge section {section_title} chunk {chunk_index} from {relative_path}.",
    }


def split_markdown_sections(content: str, fallback_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading_stack: list[str] = []
    current_lines: list[str] = []
    current_title = fallback_title

    def flush_current() -> None:
        nonlocal current_lines, current_title
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_title, body))
        current_lines = []

    for raw_line in content.splitlines():
        match = HEADING_PATTERN.match(raw_line)
        if match:
            flush_current()
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack[:] = heading_stack[: level - 1]
            heading_stack.append(title)
            current_title = " / ".join(heading_stack)
            continue

        current_lines.append(raw_line)

    flush_current()
    return sections


def load_knowledge_payloads(knowledge_dir: Path) -> list[dict]:
    payloads: list[dict] = []
    if not knowledge_dir.exists():
        return payloads

    for path in sorted(knowledge_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8-sig")
        sections = split_markdown_sections(content, path.stem)
        if not sections:
            sections = [(path.stem, content)]
        for index, (section_title, section_body) in enumerate(sections, start=1):
            chunks = split_large_text(section_body)
            for chunk_index, chunk_body in enumerate(chunks, start=1):
                payloads.append(build_knowledge_payload(path, section_title, section_body, index, chunk_index, chunk_body))
    return payloads


def build_transcript_payload(path: Path, chunk_index: int, chunk_body: str) -> dict:
    relative_path = str(path.relative_to(ROOT_DIR)).replace("\\", "/")
    name = path.stem
    summary = collapse_whitespace(chunk_body, 500)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "transcript-import",
        "turn_id": f"{name}-chunk-{chunk_index:03d}",
        "source_type": "transcript",
        "source_name": path.stem,
        "user_request": f"Transcript import: {path.stem}",
        "summary": summary,
        "constraints": [],
        "files_read": [relative_path],
        "files_changed": [],
        "knowledge_sources": [],
        "decisions": [f"Indexed transcript chunk {chunk_index}"],
        "open_questions": [],
        "outcome": f"Indexed transcript chunk {chunk_index} from {relative_path}.",
    }


def load_transcript_payloads(transcript_dir: Path) -> list[dict]:
    payloads: list[dict] = []
    if not transcript_dir.exists():
        return payloads

    for path in sorted(transcript_dir.glob("*.txt")):
        content = path.read_text(encoding="utf-8-sig")
        for chunk_index, chunk_body in enumerate(split_large_text(content), start=1):
            payloads.append(build_transcript_payload(path, chunk_index, chunk_body))
    return payloads


def chunk_external_record(record: dict[str, Any]) -> list[dict]:
    text_parts = [
        str(record.get("user_request") or ""),
        str(record.get("summary") or ""),
        str(record.get("outcome") or ""),
        "\n".join(str(item) for item in record.get("decisions") or []),
        "\n".join(str(item) for item in record.get("files_read") or []),
        "\n".join(str(item) for item in record.get("knowledge_sources") or []),
    ]
    chunks = split_large_text("\n\n".join(part for part in text_parts if part.strip()))
    if len(chunks) <= 1:
        return [record]

    results: list[dict] = []
    base_turn_id = str(record.get("turn_id") or "external")
    decisions = [str(item) for item in record.get("decisions") or []]
    for chunk_index, chunk_body in enumerate(chunks, start=1):
        chunk_record = dict(record)
        chunk_record["turn_id"] = f"{base_turn_id}-chunk-{chunk_index:03d}"
        chunk_record["summary"] = collapse_whitespace(chunk_body, 500)
        chunk_record["decisions"] = decisions + [f"External chunk {chunk_index}"]
        results.append(chunk_record)
    return results


def load_external_payloads(external_dir: Path) -> list[dict]:
    payloads: list[dict] = []
    if not external_dir.exists():
        return payloads

    for path in sorted(external_dir.rglob("*.json")):
        content = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(content, dict) and "records" in content:
            records = content["records"]
        elif isinstance(content, list):
            records = content
        else:
            records = [content]

        for record in records:
            if not isinstance(record, dict):
                continue
            record.setdefault("source_type", "external")
            record.setdefault("source_name", path.stem)
            record.setdefault("session_id", f"{record['source_type']}-import")
            payloads.extend(chunk_external_record(record))

    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex the Chroma memory store from saved payloads and knowledge files.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Persistent Chroma database path.")
    parser.add_argument("--collection", default=get_default_collection_name(), help="Chroma collection name.")
    parser.add_argument("--payload-dir", default=str(DEFAULT_PAYLOAD_DIR), help="Directory of saved turn payload JSON files.")
    parser.add_argument("--transcript-dir", default=str(DEFAULT_TRANSCRIPT_DIR), help="Directory of saved raw transcript files.")
    parser.add_argument("--knowledge-dir", default=str(DEFAULT_KNOWLEDGE_DIR), help="Directory of markdown knowledge files.")
    parser.add_argument("--external-dir", default=str(DEFAULT_EXTERNAL_DIR), help="Directory of normalized external source JSON files.")
    parser.add_argument("--payloads-only", action="store_true", help="Reindex saved turn payloads only.")
    parser.add_argument("--knowledge-only", action="store_true", help="Reindex knowledge markdown only.")
    parser.add_argument("--transcripts-only", action="store_true", help="Reindex saved transcript text only.")
    parser.add_argument("--external-only", action="store_true", help="Reindex normalized external sources only.")
    args = parser.parse_args()

    only_flags = [args.payloads_only, args.knowledge_only, args.transcripts_only, args.external_only]
    if sum(1 for flag in only_flags if flag) > 1:
        raise SystemExit("Use at most one of --payloads-only, --knowledge-only, --transcripts-only, or --external-only.")

    imported = {"payload_records": 0, "knowledge_records": 0, "transcript_records": 0, "external_records": 0}

    if not args.knowledge_only and not args.transcripts_only and not args.external_only:
        for payload in load_payloads(Path(args.payload_dir)):
            upsert_payload(payload, db_path=Path(args.db_path), collection_name=args.collection)
            imported["payload_records"] += 1

    if not args.payloads_only and not args.transcripts_only and not args.external_only:
        for payload in load_knowledge_payloads(Path(args.knowledge_dir)):
            upsert_payload(payload, db_path=Path(args.db_path), collection_name=args.collection)
            imported["knowledge_records"] += 1

    if not args.payloads_only and not args.knowledge_only and not args.external_only:
        for payload in load_transcript_payloads(Path(args.transcript_dir)):
            upsert_payload(payload, db_path=Path(args.db_path), collection_name=args.collection)
            imported["transcript_records"] += 1

    if not args.payloads_only and not args.knowledge_only and not args.transcripts_only:
        for payload in load_external_payloads(Path(args.external_dir)):
            upsert_payload(payload, db_path=Path(args.db_path), collection_name=args.collection)
            imported["external_records"] += 1

    imported["collection"] = args.collection
    imported["db_path"] = str(Path(args.db_path).resolve())
    print(json.dumps(imported, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
