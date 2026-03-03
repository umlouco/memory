# Chroma Memory Workflow

This directory provides a concrete Chroma-backed memory path for agent turns in this repository.

## Storage

- Default database path: `.chroma/`
- Default collection base: `chat_memory`
- Effective collection name includes the provider, for example `chat_memory_local_onnx`
- Persistence is local to this machine and survives future sessions unless `.chroma/` is deleted.
- Raw transcript captures are stored in `storage/app/memory-transcripts/`
- External normalized source exports are stored in `storage/app/memory-external/`
- Reindexing chunks long payload, knowledge, and transcript records with overlap for better retrieval

## Embeddings Provider

The default provider is Chroma's local ONNX MiniLM embedding model.

Set:

```text
MEMORY_EMBEDDING_PROVIDER=local_onnx
```

Optional ONNX runtime controls:

```text
MEMORY_ONNX_PREFERRED_PROVIDERS=DmlExecutionProvider,CPUExecutionProvider
MEMORY_ONNX_REQUIRE_GPU=true
```

Notes:

- first run may download the ONNX model files
- it is small enough to be practical on a laptop
- on Windows, DirectML can be used when `DmlExecutionProvider` is available
- `MEMORY_ONNX_REQUIRE_GPU=true` makes the process fail closed if the embedding session falls back to CPU

Inspect the live runtime binding:

```text
python tools/memory/inspect_embedding_runtime.py
```

If you want OpenAI embeddings instead, set:

```text
MEMORY_EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=<your key>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
```

If you need an offline fallback, set:

```text
MEMORY_EMBEDDING_PROVIDER=local
```

`local` is the older deterministic hash fallback. It works without downloads, but retrieval quality is lower than `local_onnx`.

`gpt-4.1` is not an embeddings model and should not be used for `OPENAI_EMBEDDING_MODEL`.

## Payload

The upsert command expects a JSON file with these fields:

```json
{
  "timestamp": "2026-03-01T16:00:00Z",
  "session_id": "copilot-session-001",
  "turn_id": "turn-001",
  "user_request": "Summarize the workflow requirements.",
  "summary": "Reviewed README and .knowledge documents.",
  "constraints": ["Do not change production config"],
  "files_read": ["README.md", ".knowledge/requirements.md"],
  "files_changed": ["AGENTS.md"],
  "knowledge_sources": [".knowledge/requirements.md", ".knowledge/architecture.md"],
  "decisions": ["Use local Chroma persistence under .chroma/"],
  "open_questions": [],
  "outcome": "Added repository-level memory instructions."
}
```

If `knowledge_sources` is omitted, the script records all markdown files currently present in `.knowledge/`.

## Commands

Write memory:

```text
python tools/memory/upsert_chat_memory.py --input <payload.json>
```

Query memory:

```text
python tools/memory/query_chat_memory.py --query "approval workflow" --session <session_id>
```

How Chroma querying works in this repository:

1. The stored records already have embeddings written during indexing or upsert.
2. A new query still needs its own embedding vector.
3. Chroma compares that query vector against stored vectors and returns nearest matches.
4. The raw database read and vector search are not accelerated by the ONNX model.
5. GPU only helps on the embedding computation step, both when writing records and when embedding the query text for retrieval.

Build a requirement contract before planning or implementation:

```text
python tools/memory/build_requirement_contract.py --query "workflow csv import export" --limit 12
```

Recall a short pre-turn brief:

```text
python tools/memory/recall_turn_context.py --query "approval workflow" --session <session_id> --limit 3
```

## Recommended Agent Architecture

Raw semantic recall is not enough for implementation safety. Use Chroma in these layers:

1. Recall gate
   Run `enforce_memory_recall.py` first so the turn cannot proceed without consulting memory.
2. Requirement contract
   Run `build_requirement_contract.py` against authoritative sources like `requirements`, `confluence`, and `jira`.
   Treat its output as a checklist of obligations, not as optional background.
3. Plan against coverage
   Every implementation plan should map work items to requirement-contract lines with explicit status such as `addressed`, `deferred`, or `open-question`.
4. Implement and verify
   Tests and review notes should cite the requirement lines they satisfy.
5. Persist outcome
   Write the final memory payload only after the delivered work and any unmet requirements are recorded.

This architecture closes the gap where an agent recalls relevant context but never promotes it into a mandatory execution contract. A missed item like CSV import/export should now appear as an `unaddressed` requirement before coding begins.

Fail closed unless Chroma recall runs first:

```text
python tools/memory/enforce_memory_recall.py --query "approval workflow" --run powershell -Command "Get-Date"
```

Filter recall by session prefix and date range:

```text
python tools/memory/recall_turn_context.py --query "approval workflow" --session-prefix transcript- --date-from 2026-03-01 --date-to 2026-03-01 --limit 5
```

Filter recall to one source:

```text
python tools/memory/recall_turn_context.py --query "bulk editing" --source requirements --limit 3
```

Filter recall by source type:

```text
python tools/memory/recall_turn_context.py --query "future transcripts automatically" --source-type transcript --limit 3
```

Reindex the fresh store from saved turn payloads and `.knowledge` files:

```text
python tools/memory/reindex_memory_store.py
```

Reindex only saved turn payloads:

```text
python tools/memory/reindex_memory_store.py --payloads-only
```

Reindex only `.knowledge` markdown:

```text
python tools/memory/reindex_memory_store.py --knowledge-only
```

Reindex only saved transcript text:

```text
python tools/memory/reindex_memory_store.py --transcripts-only
```

Reindex only external normalized sources:

```text
python tools/memory/reindex_memory_store.py --external-only
```

Reset `.chroma` and rebuild everything in one command:

```text
powershell -ExecutionPolicy Bypass -File tools/memory/rebuild_memory_store.ps1
```

Export a local git repository into normalized memory records:

```text
python tools/memory/export_git_repository_to_memory.py --repo-path /path/to/repo
```

Fetch Jira issues into normalized memory records:

```text
python tools/memory/fetch_jira_to_memory.py --jql "project = MYPROJECT ORDER BY updated DESC"
```

Fetch Confluence pages into normalized memory records:

```text
python tools/memory/fetch_confluence_to_memory.py --space-id 123456
```

After exporting or fetching external sources, run:

```text
python tools/memory/reindex_memory_store.py --external-only
```

Fail-closed enforcement:

```text
python tools/memory/enforce_memory_write.py --input <payload.json>
```

Optional wrapped command:

```text
python tools/memory/enforce_memory_write.py --input <payload.json> --run python -m pytest
```

The wrapper returns a non-zero exit code if the wrapped command fails, but it still attempts the Chroma write first so the failure is preserved in memory.

PowerShell launcher with automatic payload generation:

```text
powershell -ExecutionPolicy Bypass -File tools/memory/run_memory_guard.ps1 `
  -SessionId copilot-session `
  -UserRequest "Review workflow approval logic" `
  -QueryMemory "workflow approval" `
  -RequireRecallFirst `
  -RunCommand "Get-Date"
```

If you explicitly want recall limited to one prior session, add:

```text
-RecallSession <session_id>
```

Transcript file capture:

```text
powershell -ExecutionPolicy Bypass -File tools/memory/run_memory_guard.ps1 `
  -SessionId copilot-session `
  -TranscriptPath .\chat.txt `
  -RunCommand "Get-Date"
```

Transcript stdin capture:

```text
Get-Content .\chat.txt -Raw | powershell -ExecutionPolicy Bypass -File tools/memory/run_memory_guard.ps1 `
  -SessionId copilot-session `
  -TranscriptFromStdin `
  -RunCommand "Get-Date"
```

If `-Summary` or `-Outcome` are omitted, they are generated automatically. If `-FilesChanged` is omitted, the payload builder derives it from `git status --short`. Payload JSON files are written to `storage/app/memory-payloads/` and then passed to the enforcement wrapper. If a transcript is provided, the launcher also saves a raw copy into `storage/app/memory-transcripts/` for later reindexing.

## Runner Template

The repository includes a VS Code task template in `tools/memory/tasks.vscode.json` with:

- `memory:recall` for pre-turn recall
- `memory:guarded-command` for a completion-gated command
- `memory:import-jira` for Jira issue import
- `memory:import-confluence` for Confluence page import
- `memory:import-git-connexall` for local `git.connexall.com` repository export

It is a template rather than a live editor config because many environments ignore or override shared `.vscode` settings.
