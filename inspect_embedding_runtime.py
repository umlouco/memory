from __future__ import annotations

import argparse
import json
import sys

from chroma_memory import (
    embed_text,
    get_embedding_provider,
    get_local_onnx_runtime_details,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the active embedding runtime and provider binding.")
    parser.add_argument(
        "--probe-text",
        default="embedding runtime probe",
        help="Text used to force lazy embedding session initialization.",
    )
    args = parser.parse_args()

    provider = get_embedding_provider()
    details: dict[str, object] = {
        "embedding_provider": provider,
    }

    if provider == "local_onnx":
        embed_text(args.probe_text)
        details.update(get_local_onnx_runtime_details())
    else:
        details["message"] = "Detailed runtime inspection is currently only available for MEMORY_EMBEDDING_PROVIDER=local_onnx."

    json.dump(details, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
