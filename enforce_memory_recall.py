from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from chroma_memory import DEFAULT_DB_PATH, get_default_collection_name, query_memory


def has_recall_hits(query: str, db_path: Path, collection: str, session_id: str | None, limit: int) -> tuple[bool, dict]:
    result = query_memory(
        query=query,
        db_path=db_path,
        collection_name=collection,
        limit=limit,
        session_id=session_id,
    )
    ids = result.get("ids") or [[]]
    return bool(ids and ids[0]), result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless Chroma recall is consulted before continuing."
    )
    parser.add_argument("--query", required=True, help="Recall query to run before task execution.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Persistent Chroma database path.")
    parser.add_argument("--collection", default=get_default_collection_name(), help="Chroma collection name.")
    parser.add_argument("--session", help="Optional session identifier filter for recall.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of recall results.")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow the command to continue even if recall returns no hits, as long as recall executed successfully.",
    )
    parser.add_argument(
        "--run",
        nargs=argparse.REMAINDER,
        help="Optional command to run after successful recall. Pass it after --run.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    has_hits, result = has_recall_hits(args.query, db_path, args.collection, args.session, args.limit)
    output = {
        "recall_executed": True,
        "query": args.query,
        "collection": args.collection,
        "db_path": str(db_path.resolve()),
        "result_count": len((result.get("ids") or [[]])[0]),
        "allow_empty": args.allow_empty,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")

    if not has_hits and not args.allow_empty:
        sys.stderr.write("Chroma recall returned no results. Refusing to continue without prior memory context.\n")
        return 2

    if args.run:
        completed = subprocess.run(args.run, check=False)
        return completed.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
