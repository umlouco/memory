from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from chroma_memory import DEFAULT_DB_PATH, get_default_collection_name, load_payload, upsert_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail closed unless a turn payload is successfully written to Chroma."
    )
    parser.add_argument("--input", required=True, help="Path to a JSON payload file.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Persistent Chroma database path.")
    parser.add_argument("--collection", default=get_default_collection_name(), help="Chroma collection name.")
    parser.add_argument(
        "--run",
        nargs=argparse.REMAINDER,
        help="Optional command to run before the memory write. Pass it after --run.",
    )
    args = parser.parse_args()

    command_result = None
    if args.run:
        completed = subprocess.run(args.run, check=False, text=True, capture_output=True)
        command_result = {
            "command": args.run,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.stdout:
            sys.stdout.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            sys.stderr.write(
                f"Wrapped command failed with exit code {completed.returncode}. Memory write will still be attempted.\n"
            )

    payload = load_payload(args.input)
    if command_result:
        payload["decisions"] = list(payload.get("decisions") or []) + [
            f"Wrapped command executed: {' '.join(command_result['command'])}"
        ]
        payload["outcome"] = (
            str(payload.get("outcome") or "").strip()
            + f" Command exit code: {command_result['returncode']}."
        ).strip()

    result = upsert_payload(payload, db_path=Path(args.db_path), collection_name=args.collection)
    json.dump(
        {
            "memory_write": "verified",
            "record_id": result["id"],
            "collection": result["collection"],
            "db_path": result["db_path"],
            "wrapped_command": command_result,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")

    if command_result and command_result["returncode"] != 0:
        return command_result["returncode"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
