"""Custom MCP memory server backed by the Chroma vector database.

Exposes the same tool surface as @modelcontextprotocol/server-memory so
existing agent code (mcp_memory_read_graph, mcp_memory_search_nodes, etc.)
works unchanged — but reads and writes to the local .chroma database instead
of a separate JSONL file.

Start:
    python mcp_chroma_server.py

Configured via .vscode/mcp.json.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from mcp.server.fastmcp import FastMCP
from chroma_memory import (
    DEFAULT_DB_PATH,
    DEFAULT_COLLECTION_NAME,
    get_client,
    get_embedding_function,
    upsert_payload,
)

# ---------------------------------------------------------------------------
# Chroma helpers
# ---------------------------------------------------------------------------

_DB_PATH = Path(os.environ.get("CHROMA_DB_PATH", str(DEFAULT_DB_PATH)))
_COLLECTION = os.environ.get("CHROMA_COLLECTION", DEFAULT_COLLECTION_NAME)


def _get_collection():
    client = get_client(_DB_PATH)
    try:
        return client.get_or_create_collection(
            name=_COLLECTION,
            embedding_function=get_embedding_function(),
        )
    except Exception:
        # Fall back without embedding function (query by metadata only)
        return client.get_or_create_collection(name=_COLLECTION)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("chroma-memory")


@mcp.tool()
def read_graph() -> str:
    """Return the most recent 50 conversation turns from the Chroma memory store."""
    col = _get_collection()
    results = col.get(include=["metadatas", "documents"], limit=50)
    ids = results.get("ids") or []
    metas = results.get("metadatas") or []
    docs = results.get("documents") or []

    entities = []
    for doc_id, meta, doc in zip(ids, metas, docs):
        observations = []
        for key in ("user_request", "summary", "outcome", "files_changed", "timestamp"):
            val = (meta or {}).get(key, "")
            if val:
                observations.append(f"{key}: {str(val)[:300]}")
        if not observations and doc:
            observations.append(doc[:300])
        entities.append({
            "name": doc_id,
            "entityType": "ConversationTurn",
            "observations": observations,
        })

    return json.dumps({"entities": entities, "relations": []}, indent=2)


@mcp.tool()
def search_nodes(query: str) -> str:
    """Semantic search over stored conversation turns in Chroma.

    Args:
        query: Natural language search query.
    """
    col = _get_collection()
    try:
        results = col.query(query_texts=[query], n_results=10, include=["metadatas", "documents", "distances"])
        ids = (results.get("ids") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        docs = (results.get("documents") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]
    except Exception as e:
        return json.dumps({"error": str(e), "entities": []})

    entities = []
    for doc_id, meta, doc, dist in zip(ids, metas, docs, distances):
        observations = []
        for key in ("user_request", "summary", "outcome", "files_changed", "timestamp"):
            val = (meta or {}).get(key, "")
            if val:
                observations.append(f"{key}: {str(val)[:300]}")
        if not observations and doc:
            observations.append(doc[:300])
        entities.append({
            "name": doc_id,
            "entityType": "ConversationTurn",
            "observations": observations,
            "relevance_score": round(1.0 - float(dist), 4) if dist is not None else None,
        })

    return json.dumps({"entities": entities}, indent=2)


@mcp.tool()
def open_nodes(names: list[str]) -> str:
    """Retrieve specific turns by their IDs.

    Args:
        names: List of turn IDs (Chroma document IDs).
    """
    col = _get_collection()
    try:
        results = col.get(ids=names, include=["metadatas", "documents"])
    except Exception as e:
        return json.dumps({"error": str(e), "entities": []})

    ids = results.get("ids") or []
    metas = results.get("metadatas") or []
    docs = results.get("documents") or []

    entities = []
    for doc_id, meta, doc in zip(ids, metas, docs):
        observations = []
        for key in ("user_request", "summary", "outcome", "files_changed", "timestamp"):
            val = (meta or {}).get(key, "")
            if val:
                observations.append(f"{key}: {str(val)[:400]}")
        if not observations and doc:
            observations.append(doc[:400])
        entities.append({
            "name": doc_id,
            "entityType": "ConversationTurn",
            "observations": observations,
        })

    return json.dumps({"entities": entities}, indent=2)


@mcp.tool()
def create_entities(entities: list[dict]) -> str:
    """Store new entities into the Chroma memory store.

    Args:
        entities: List of objects with 'name', 'entityType', and 'observations'.
    """
    col = _get_collection()
    written = []
    for ent in entities:
        name = ent.get("name", "")
        observations = ent.get("observations") or []
        doc = " | ".join(str(o) for o in observations)
        meta = {
            "entityType": ent.get("entityType", "Entity"),
            "user_request": next((str(o) for o in observations if str(o).startswith("User:")), ""),
            "summary": next((str(o) for o in observations if str(o).startswith("Summary:")), ""),
            "outcome": next((str(o) for o in observations if str(o).startswith("Outcome:")), ""),
        }
        try:
            col.upsert(ids=[name], documents=[doc], metadatas=[meta])
            written.append(name)
        except Exception as e:
            written.append(f"ERROR:{name}:{e}")

    return json.dumps({"created": written})


@mcp.tool()
def add_observations(observations: list[dict]) -> str:
    """Append observations to existing entities.

    Args:
        observations: List of objects with 'entityName' and 'contents' (list of strings).
    """
    col = _get_collection()
    updated = []
    for item in observations:
        entity_name = item.get("entityName", "")
        new_obs = item.get("contents") or []
        try:
            existing = col.get(ids=[entity_name], include=["documents", "metadatas"])
            if existing["ids"]:
                old_doc = (existing["documents"] or [""])[0]
                addition = " | ".join(str(o) for o in new_obs)
                new_doc = f"{old_doc} | {addition}".strip(" |")
                col.update(ids=[entity_name], documents=[new_doc])
                updated.append(entity_name)
        except Exception as e:
            updated.append(f"ERROR:{entity_name}:{e}")

    return json.dumps({"updated": updated})


if __name__ == "__main__":
    mcp.run(transport="stdio")
