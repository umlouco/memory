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
DEFAULT_OUTPUT_DIR = ROOT_DIR / "storage" / "app" / "memory-external" / "jira"


def request_json(url: str, email: str, api_token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def build_issue_record(issue: dict[str, Any], source_name: str) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    key = str(issue.get("key") or issue.get("id") or "issue")
    summary = normalize_text(fields.get("summary"))
    description = normalize_text(fields.get("description"))
    status = normalize_text((fields.get("status") or {}).get("name"))
    issue_type = normalize_text((fields.get("issuetype") or {}).get("name"))
    project_key = normalize_text((fields.get("project") or {}).get("key"))
    labels = fields.get("labels") or []
    updated = normalize_text(fields.get("updated"))

    return {
        "timestamp": updated or datetime.now(timezone.utc).isoformat(),
        "session_id": "jira-import",
        "turn_id": key,
        "source_type": "jira",
        "source_name": source_name,
        "user_request": f"Jira issue import: {key}",
        "summary": f"{summary}\nStatus: {status}\nType: {issue_type}\nProject: {project_key}\nLabels: {', '.join(labels)}\n{description}",
        "constraints": [],
        "files_read": [],
        "files_changed": [],
        "knowledge_sources": [],
        "decisions": [f"Imported Jira issue {key}"],
        "open_questions": [],
        "outcome": f"Imported Jira issue {key}.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Jira issues and normalize them for Chroma reindexing.")
    parser.add_argument("--site-url", default=os.getenv("JIRA_SITE_URL", ""), help="Jira Cloud site URL, e.g. https://your-domain.atlassian.net")
    parser.add_argument("--email", default=os.getenv("JIRA_EMAIL", ""), help="Atlassian account email")
    parser.add_argument("--api-token", default=os.getenv("JIRA_API_TOKEN", ""), help="Atlassian API token")
    parser.add_argument("--jql", required=True, help="JQL query to fetch issues")
    parser.add_argument("--limit", type=int, default=100, help="Maximum issues to fetch")
    parser.add_argument("--output", help="Optional output file path")
    args = parser.parse_args()

    if not args.site_url or not args.email or not args.api_token:
        raise SystemExit("Jira credentials are required. Set --site-url, --email, and --api-token or the matching env vars.")

    site_url = args.site_url.rstrip("/")
    source_name = f"jira:{re.sub(r'[^a-z0-9]+', '-', args.jql.lower()).strip('-') or 'search'}"
    endpoint = f"{site_url}/rest/api/3/search/jql"
    payload = {
        "jql": args.jql,
        "maxResults": args.limit,
        "fields": ["summary", "description", "status", "issuetype", "project", "labels", "updated"],
    }
    data = request_json(endpoint, args.email, args.api_token, payload=payload)
    issues = data.get("issues") or []
    records = [build_issue_record(issue, source_name) for issue in issues]

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"{source_name.replace(':', '_')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"records": records}, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "records": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    import re
    raise SystemExit(main())
