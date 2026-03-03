from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chroma_memory import DEFAULT_DB_PATH, get_default_collection_name, query_memory


def main() -> int:
    parser = argparse.ArgumentParser(description="Query chat memory stored in Chroma.")
    parser.add_argument("--query", required=True, help="Natural language query.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Persistent Chroma database path.")
    parser.add_argument("--collection", default=get_default_collection_name(), help="Chroma collection name.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of results.")
    parser.add_argument("--session", help="Optional session identifier filter.")
    args = parser.parse_args()

    result = query_memory(
        query=args.query,
        db_path=Path(args.db_path),
        collection_name=args.collection,
        limit=args.limit,
        session_id=args.session,
    )
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
