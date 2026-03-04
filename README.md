# Chat Memory

Chroma-backed semantic memory for GitHub Copilot chat sessions. Every prompt is logged and recalled automatically via VS Code Copilot hooks, powered by a local LM Studio embedding model.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **Python 3.11+** | Must be on PATH |
| **LM Studio** | Running on `localhost:1234` with **qwen3-embedding-0.6b** loaded |
| **VS Code** | With GitHub Copilot Chat extension |

## Quick Start

Clone this repo somewhere permanent (e.g. `D:\git\chat-memory`), then run the setup script pointing at **any workspace** you want to wire up:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -TargetWorkspace "D:\git\my-project"
```

This will:

1. Create a `.venv` and install `chromadb` + `openai`
2. Write Copilot hook entries into `<workspace>/.vscode/settings.json`
3. Verify the LM Studio embedding endpoint is reachable

To wire up **another** workspace later, just run the same command with a different path. The venv is shared — it only gets created once.

### Manual Setup

If you prefer to set things up by hand:

```powershell
# 1. Create venv & install deps
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Verify LM Studio
python inspect_embedding_runtime.py
```

Then add these hooks to your workspace's `.vscode/settings.json`:

```json
{
  "github.copilot.chat.hooks": [
    {
      "event": "userPromptSubmit",
      "command": "D:/git/chat-memory/.venv/Scripts/python.exe D:/git/chat-memory/hook_get_context.py"
    },
    {
      "event": "userPromptSubmit",
      "command": "D:/git/chat-memory/.venv/Scripts/python.exe D:/git/chat-memory/hook_log_prompt.py"
    }
  ]
}
```

Replace `D:/git/chat-memory` with the actual path where you cloned this repo.

## How It Works

Two Copilot hooks fire on every `userPromptSubmit`:

| Hook | Purpose |
|------|---------|
| `hook_get_context.py` | Queries Chroma for related past turns and injects a `<memory_context>` block |
| `hook_log_prompt.py` | Writes the current prompt into Chroma for future recall |

Both hooks are silent — they never block or fail your prompt.

## Configuration

All optional. Defaults work if LM Studio is on `localhost:1234`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LM_STUDIO_API_BASE` | `http://localhost:1234/v1` | LM Studio API endpoint |
| `LM_STUDIO_MODEL` | `qwen3-embedding-0.6b` | Embedding model ID in LM Studio |
| `LM_STUDIO_API_KEY` | `lm-studio` | API key (LM Studio ignores this) |

## Storage

| Path | Contents |
|------|----------|
| `.chroma/` | Chroma vector database (gitignored) |
| `storage/app/memory-payloads/` | Saved turn payload JSONs |
| `storage/app/memory-transcripts/` | Raw transcript text files |

Collection: `agent_memory` with cosine similarity (`hnsw:space: cosine`).

## Commands Reference

```powershell
# Write a memory payload
python upsert_chat_memory.py --input payload.json

# Query memory
python query_chat_memory.py --query "approval workflow" --limit 5

# Recall brief (human-readable)
python recall_turn_context.py --query "approval workflow" --limit 3

# Reindex from saved payloads + .knowledge files
python reindex_memory_store.py

# Reset .chroma and rebuild everything
powershell -ExecutionPolicy Bypass -File rebuild_memory_store.ps1

# Probe LM Studio endpoint
python inspect_embedding_runtime.py
```

### Enforcement Commands

```powershell
# Fail-closed write (must succeed)
python enforce_memory_write.py --input payload.json

# Fail-closed recall gate (must run before task)
python enforce_memory_recall.py --query "workflow" --run python my_script.py

# Full guarded workflow with auto-generated payload
powershell -ExecutionPolicy Bypass -File run_memory_guard.ps1 `
  -SessionId copilot-session `
  -UserRequest "Review workflow" `
  -QueryMemory "workflow" `
  -RequireRecallFirst
```

### Filtering Recall

```powershell
# By date range
python recall_turn_context.py --query "workflow" `
  --date-from 2026-03-01 --date-to 2026-03-04

# By source name or type
python recall_turn_context.py --query "editing" --source requirements
python recall_turn_context.py --query "transcripts" --source-type transcript
```

## VS Code Task Template

Copy `tasks.vscode.json` into `.vscode/tasks.json` for quick-access tasks: `memory:recall` and `memory:guarded-command`.
