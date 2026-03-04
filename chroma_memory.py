from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / ".chroma"
DEFAULT_COLLECTION_NAME = "agent_memory"
DEFAULT_LM_STUDIO_API_BASE = "http://localhost:1234/v1"
DEFAULT_LM_STUDIO_MODEL = "qwen3-embedding-0.6b"


@dataclass
class MemoryRecord:
    record_id: str
    document: str
    metadata: dict[str, Any]


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def get_embedding_function() -> OpenAIEmbeddingFunction:
    """Return an OpenAIEmbeddingFunction pointing at the local LM Studio instance."""
    api_base = os.getenv("LM_STUDIO_API_BASE", DEFAULT_LM_STUDIO_API_BASE)
    model_name = os.getenv("LM_STUDIO_MODEL", DEFAULT_LM_STUDIO_MODEL)
    api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
    return OpenAIEmbeddingFunction(
        api_key=api_key,
        api_base=api_base,
        model_name=model_name,
    )


def _repo_name(root_dir: Path) -> str:
    return root_dir.name


def _knowledge_documents(root_dir: Path) -> list[str]:
    knowledge_dir = root_dir / ".knowledge"
    if not knowledge_dir.exists():
        return []
    return sorted(str(path.relative_to(root_dir)).replace("\\", "/") for path in knowledge_dir.glob("*.md"))


def _git_branch(root_dir: Path) -> str:
    head_path = root_dir / ".git" / "HEAD"
    if not head_path.exists():
        return "unknown"

    content = head_path.read_text(encoding="utf-8").strip()
    if content.startswith("ref: refs/heads/"):
        return content.removeprefix("ref: refs/heads/")
    return content[:12] if content else "unknown"


def get_default_collection_name() -> str:
    return DEFAULT_COLLECTION_NAME


def get_client(db_path: Path | str = DEFAULT_DB_PATH) -> chromadb.PersistentClient:
    db_path = Path(db_path)
    db_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(db_path))


def get_collection(
    client: chromadb.PersistentClient,
    collection_name: str | None = None,
):
    resolved_name = collection_name or get_default_collection_name()
    ef = get_embedding_function()
    return client.get_or_create_collection(
        name=resolved_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def build_record(payload: dict[str, Any], root_dir: Path = ROOT_DIR) -> MemoryRecord:
    session_id = str(payload.get("session_id") or "default-session")
    turn_id = str(payload.get("turn_id") or payload.get("timestamp") or "turn")
    record_id = f"{session_id}:{turn_id}"

    normalized_payload = {
        "timestamp": str(payload.get("timestamp") or ""),
        "session_id": session_id,
        "turn_id": turn_id,
        "source_type": str(payload.get("source_type") or ""),
        "source_name": str(payload.get("source_name") or ""),
        "user_request": str(payload.get("user_request") or ""),
        "summary": str(payload.get("summary") or ""),
        "constraints": _normalize_list(payload.get("constraints")),
        "files_read": _normalize_list(payload.get("files_read")),
        "files_changed": _normalize_list(payload.get("files_changed")),
        "knowledge_sources": _normalize_list(payload.get("knowledge_sources")) or _knowledge_documents(root_dir),
        "decisions": _normalize_list(payload.get("decisions")),
        "open_questions": _normalize_list(payload.get("open_questions")),
        "outcome": str(payload.get("outcome") or ""),
        "repo_name": str(payload.get("repo_name") or _repo_name(root_dir)),
        "repo_root": str(payload.get("repo_root") or root_dir),
        "git_branch": str(payload.get("git_branch") or _git_branch(root_dir)),
    }

    summary_lines = [
        f"User request: {normalized_payload['user_request']}",
        f"Summary: {normalized_payload['summary']}",
        f"Constraints: {', '.join(normalized_payload['constraints']) or 'none'}",
        f"Files read: {', '.join(normalized_payload['files_read']) or 'none'}",
        f"Files changed: {', '.join(normalized_payload['files_changed']) or 'none'}",
        f"Knowledge sources: {', '.join(normalized_payload['knowledge_sources']) or 'none'}",
        f"Decisions: {', '.join(normalized_payload['decisions']) or 'none'}",
        f"Open questions: {', '.join(normalized_payload['open_questions']) or 'none'}",
        f"Outcome: {normalized_payload['outcome']}",
    ]
    document = "\n".join(summary_lines)

    metadata = {
        "timestamp": normalized_payload["timestamp"],
        "session_id": session_id,
        "turn_id": turn_id,
        "repo_name": normalized_payload["repo_name"],
        "repo_root": normalized_payload["repo_root"],
        "git_branch": normalized_payload["git_branch"],
        "source_type": normalized_payload["source_type"][:100],
        "source_name": normalized_payload["source_name"][:200],
        "user_request": normalized_payload["user_request"][:500],
        "summary": normalized_payload["summary"][:500],
        "outcome": normalized_payload["outcome"][:500],
        "embedding_provider": "lm_studio",
        "files_read_count": len(normalized_payload["files_read"]),
        "files_changed_count": len(normalized_payload["files_changed"]),
        "knowledge_source_count": len(normalized_payload["knowledge_sources"]),
        "payload_json": json.dumps(normalized_payload, ensure_ascii=True),
    }

    return MemoryRecord(record_id=record_id, document=document, metadata=metadata)


def upsert_payload(
    payload: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
    collection_name: str | None = None,
) -> dict[str, Any]:
    client = get_client(db_path)
    resolved_collection_name = collection_name or get_default_collection_name()
    collection = get_collection(client, resolved_collection_name)
    record = build_record(payload)

    collection.upsert(
        ids=[record.record_id],
        documents=[record.document],
        metadatas=[record.metadata],
    )

    verification = collection.get(ids=[record.record_id], include=["metadatas", "documents"])
    if not verification.get("ids"):
        raise RuntimeError(f"Chroma verification failed for record {record.record_id}")

    return {
        "id": record.record_id,
        "collection": resolved_collection_name,
        "db_path": str(Path(db_path).resolve()),
        "document": record.document,
        "metadata": record.metadata,
    }


def query_memory(
    query: str,
    db_path: Path | str = DEFAULT_DB_PATH,
    collection_name: str | None = None,
    limit: int = 5,
    session_id: str | None = None,
) -> dict[str, Any]:
    client = get_client(db_path)
    collection = get_collection(client, collection_name or get_default_collection_name())
    where = {"session_id": session_id} if session_id else None
    result = collection.query(
        query_texts=[query],
        n_results=limit,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return result


def flatten_query_results(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids = result.get("ids") or [[]]
    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]

    flattened: list[dict[str, Any]] = []
    for index, record_id in enumerate(ids[0]):
        metadata = metadatas[0][index] if metadatas and metadatas[0] else {}
        payload = {}
        payload_json = metadata.get("payload_json") if isinstance(metadata, dict) else None
        if payload_json:
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError:
                payload = {}

        flattened.append(
            {
                "id": record_id,
                "document": documents[0][index] if documents and documents[0] else "",
                "metadata": metadata,
                "distance": distances[0][index] if distances and distances[0] else None,
                "payload": payload,
            }
        )
    return flattened
 

def load_payload(path: str | os.PathLike[str]) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
