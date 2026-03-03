from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "storage" / "app" / "memory-external" / "confluence"


def request_json(url: str, email: str, api_token: str) -> dict[str, Any]:
    token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def html_to_text(value: str) -> str:
    return (
        value.replace("<br />", "\n")
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
        .replace("</p>", "\n")
        .replace("</li>", "\n")
        .replace("&nbsp;", " ")
    )


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return html_to_text(value)
    return json.dumps(value, ensure_ascii=False)


def build_page_record(page: dict[str, Any], source_name: str) -> dict[str, Any]:
    page_id = str(page.get("id") or "page")
    title = normalize_text(page.get("title"))
    body = normalize_text(((page.get("body") or {}).get("storage") or {}).get("value"))
    created_at = normalize_text(page.get("createdAt")) or datetime.now(timezone.utc).isoformat()
    space_id = normalize_text(page.get("spaceId"))

    return {
        "timestamp": created_at,
        "session_id": "confluence-import",
        "turn_id": page_id,
        "source_type": "confluence",
        "source_name": source_name,
        "user_request": f"Confluence page import: {title}",
        "summary": f"Title: {title}\nSpace: {space_id}\n{body}",
        "constraints": [],
        "files_read": [],
        "files_changed": [],
        "knowledge_sources": [],
        "decisions": [f"Imported Confluence page {page_id}"],
        "open_questions": [],
        "outcome": f"Imported Confluence page {page_id}.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Confluence pages and normalize them for Chroma reindexing.")
    parser.add_argument("--site-url", default=os.getenv("CONFLUENCE_SITE_URL", ""), help="Confluence site URL, e.g. https://your-domain.atlassian.net")
    parser.add_argument("--email", default=os.getenv("CONFLUENCE_EMAIL", ""), help="Atlassian account email")
    parser.add_argument("--api-token", default=os.getenv("CONFLUENCE_API_TOKEN", ""), help="Atlassian API token")
    parser.add_argument("--space-id", help="Optional Confluence space id")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of pages to fetch")
    parser.add_argument("--output", help="Optional output file path")
    args = parser.parse_args()

    if not args.site_url or not args.email or not args.api_token:
        raise SystemExit("Confluence credentials are required. Set --site-url, --email, and --api-token or the matching env vars.")

    site_url = args.site_url.rstrip("/")
    params = {"limit": str(args.limit), "body-format": "storage"}
    if args.space_id:
        params["space-id"] = args.space_id
    endpoint = f"{site_url}/wiki/api/v2/pages?{urllib.parse.urlencode(params)}"
    data = request_json(endpoint, args.email, args.api_token)
    pages = data.get("results") or []
    source_name = f"confluence:{args.space_id or 'pages'}"
    records = [build_page_record(page, source_name) for page in pages]

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"{source_name.replace(':', '_')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"records": records}, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "records": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
