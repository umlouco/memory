from __future__ import annotations

import argparse
import json
import sys

from chroma_memory import (
    get_embedding_function,
    DEFAULT_LM_STUDIO_API_BASE,
    DEFAULT_LM_STUDIO_MODEL,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the active embedding runtime and provider binding.")
    parser.add_argument(
        "--probe-text",
        default="embedding runtime probe",
        help="Text used to test the embedding endpoint.",
    )
    args = parser.parse_args()

    ef = get_embedding_function()
    details: dict[str, object] = {
        "embedding_provider": "lm_studio",
        "api_base": DEFAULT_LM_STUDIO_API_BASE,
        "model_name": DEFAULT_LM_STUDIO_MODEL,
    }

    try:
        result = ef([args.probe_text])
        details["probe_success"] = True
        details["embedding_dimensions"] = len(result[0]) if result else None
    except Exception as exc:
        details["probe_success"] = False
        details["probe_error"] = str(exc)

    json.dump(details, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
