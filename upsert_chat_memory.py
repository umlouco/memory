from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chroma_memory import DEFAULT_DB_PATH, get_default_collection_name, load_payload, upsert_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert a chat memory payload into Chroma.")
    parser.add_argument("--input", required=True, help="Path to a JSON payload file.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Persistent Chroma database path.")
    parser.add_argument("--collection", default=get_default_collection_name(), help="Chroma collection name.")
    args = parser.parse_args()

    payload = load_payload(args.input)
    result = upsert_payload(payload, db_path=Path(args.db_path), collection_name=args.collection)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
