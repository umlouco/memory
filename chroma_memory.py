from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
import onnxruntime as ort
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / ".chroma"
DEFAULT_COLLECTION_BASE = "chat_memory"
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_./:-]+")
EMBEDDING_DIMENSIONS = 64
DEFAULT_EMBEDDING_PROVIDER = "local_onnx"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_LOCAL_ONNX_EMBEDDER: ONNXMiniLM_L6_V2 | None = None
GPU_PROVIDER_TOKENS = {
    "cudaexecutionprovider",
    "dmlexecutionprovider",
    "tensorrtexecutionprovider",
    "rocmexecutionprovider",
    "coremlexecutionprovider",
}


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


def _stable_hash(token: str) -> int:
    value = 2166136261
    for char in token.encode("utf-8", errors="ignore"):
        value ^= char
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def embed_text_local(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    tokens = TOKEN_PATTERN.findall(text.lower())

    if not tokens:
        vector[0] = 1.0
        return vector

    for token in tokens:
        hashed = _stable_hash(token)
        index = hashed % dimensions
        sign = -1.0 if hashed & 1 else 1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        vector[0] = 1.0
        norm = 1.0

    return [value / norm for value in vector]


def get_embedding_provider() -> str:
    return os.getenv("MEMORY_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER).strip().lower()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_onnx_available_providers() -> list[str]:
    return list(ort.get_available_providers())


def get_onnx_preferred_providers() -> list[str]:
    configured = os.getenv("MEMORY_ONNX_PREFERRED_PROVIDERS", "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]

    available = get_onnx_available_providers()
    preferred: list[str] = []

    for candidate in (
        "DmlExecutionProvider",
        "CUDAExecutionProvider",
        "TensorrtExecutionProvider",
        "ROCMExecutionProvider",
        "CoreMLExecutionProvider",
        "CPUExecutionProvider",
    ):
        if candidate in available and candidate not in preferred:
            preferred.append(candidate)

    return preferred or ["CPUExecutionProvider"]


def require_onnx_gpu() -> bool:
    return _env_flag("MEMORY_ONNX_REQUIRE_GPU", default=False)


def _is_gpu_provider(provider_name: str) -> bool:
    return provider_name.strip().lower() in GPU_PROVIDER_TOKENS


def get_local_onnx_runtime_details() -> dict[str, Any]:
    embedder = get_local_onnx_embedder()
    model = embedder.model
    providers = list(model.get_providers())
    return {
        "available_providers": get_onnx_available_providers(),
        "preferred_providers": get_onnx_preferred_providers(),
        "session_providers": providers,
        "provider_options": model.get_provider_options(),
        "gpu_active": any(_is_gpu_provider(provider) for provider in providers),
        "gpu_required": require_onnx_gpu(),
    }


def get_default_collection_name(provider: str | None = None) -> str:
    resolved_provider = provider or get_embedding_provider()
    return f"{DEFAULT_COLLECTION_BASE}_{resolved_provider}"


def get_openai_embedding_model() -> str:
    requested = os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBEDDING_MODEL).strip()
    if requested.lower().startswith("gpt-4.1"):
        raise ValueError(
            "gpt-4.1 is not an embeddings model. Use an embeddings model such as text-embedding-3-large."
        )
    return requested


def embed_text_openai(text: str) -> list[float]:
    model = get_openai_embedding_model()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required when MEMORY_EMBEDDING_PROVIDER=openai")

    base_url = os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/")
    request_body = json.dumps({"input": text, "model": model}).encode("utf-8")
    request = urllib.request.Request(
        url=f"{base_url}/embeddings",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"OpenAI embeddings request failed: HTTP {exc.code} {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI embeddings request failed: {exc.reason}") from exc

    data = response_data.get("data") or []
    if not data or "embedding" not in data[0]:
        raise RuntimeError("OpenAI embeddings response did not include an embedding vector")

    return [float(value) for value in data[0]["embedding"]]


def get_local_onnx_embedder() -> ONNXMiniLM_L6_V2:
    global _LOCAL_ONNX_EMBEDDER
    if _LOCAL_ONNX_EMBEDDER is None:
        preferred_providers = get_onnx_preferred_providers()
        _LOCAL_ONNX_EMBEDDER = ONNXMiniLM_L6_V2(preferred_providers=preferred_providers)
    return _LOCAL_ONNX_EMBEDDER


def embed_text_local_onnx(text: str) -> list[float]:
    embedder = get_local_onnx_embedder()
    result = [float(value) for value in embedder([text])[0]]
    if require_onnx_gpu():
        runtime_details = get_local_onnx_runtime_details()
        if not runtime_details["gpu_active"]:
            raise RuntimeError(
                "MEMORY_ONNX_REQUIRE_GPU=true but the ONNX embedding session did not bind a GPU execution provider. "
                f"Available providers: {runtime_details['available_providers']}; "
                f"session providers: {runtime_details['session_providers']}"
            )
    return result


def embed_text(text: str) -> list[float]:
    provider = get_embedding_provider()
    if provider == "local":
        return embed_text_local(text)
    if provider == "local_onnx":
        return embed_text_local_onnx(text)
    if provider == "openai":
        return embed_text_openai(text)
    raise ValueError(f"Unsupported MEMORY_EMBEDDING_PROVIDER: {provider}")


def get_client(db_path: Path | str = DEFAULT_DB_PATH) -> chromadb.PersistentClient:
    db_path = Path(db_path)
    db_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(db_path))


def get_collection(
    client: chromadb.PersistentClient,
    collection_name: str | None = None,
):
    resolved_name = collection_name or get_default_collection_name()
    return client.get_or_create_collection(name=resolved_name, metadata={"description": "Chat memory"})


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
        "embedding_provider": get_embedding_provider(),
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
    embedding = embed_text(record.document)

    collection.upsert(
        ids=[record.record_id],
        documents=[record.document],
        embeddings=[embedding],
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
        query_embeddings=[embed_text(query)],
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
