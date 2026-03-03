from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "storage" / "app" / "memory-external" / "git"


def run_git(repo_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def build_commit_records(repo_path: Path, source_name: str, limit: int) -> list[dict]:
    fmt = "%H%x1f%aI%x1f%s%x1f%b%x1e"
    output = run_git(repo_path, "log", f"-n{limit}", f"--pretty=format:{fmt}")
    records: list[dict] = []
    for chunk in output.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split("\x1f")
        if len(parts) < 4:
            continue
        commit_hash, authored_at, subject, body = parts[:4]
        records.append(
            {
                "timestamp": authored_at or datetime.now(timezone.utc).isoformat(),
                "session_id": "git-import",
                "turn_id": commit_hash[:12],
                "source_type": "git",
                "source_name": source_name,
                "user_request": f"Git commit import: {subject}",
                "summary": f"Commit: {subject}\nHash: {commit_hash}\n{body.strip()}",
                "constraints": [],
                "files_read": [],
                "files_changed": [],
                "knowledge_sources": [],
                "decisions": [f"Imported git commit {commit_hash[:12]}"],
                "open_questions": [],
                "outcome": f"Imported git commit {commit_hash[:12]}.",
            }
        )
    return records


def build_doc_records(repo_path: Path, source_name: str, patterns: list[str]) -> list[dict]:
    files: list[str] = []
    for pattern in patterns:
        output = run_git(repo_path, "ls-files", pattern)
        files.extend(line.strip() for line in output.splitlines() if line.strip())

    unique_files = sorted(set(files))
    records: list[dict] = []
    for relative in unique_files:
        path = repo_path / relative
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        summary = " ".join(content.split())
        summary = summary[:500] if len(summary) <= 500 else summary[:497].rstrip() + "..."
        records.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": "git-import",
                "turn_id": relative.replace("/", "-").replace("\\", "-"),
                "source_type": "git",
                "source_name": source_name,
                "user_request": f"Git file import: {relative}",
                "summary": summary,
                "constraints": [],
                "files_read": [relative],
                "files_changed": [],
                "knowledge_sources": [],
                "decisions": [f"Imported git file {relative}"],
                "open_questions": [],
                "outcome": f"Imported git file {relative}.",
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Export git repository commits and docs into normalized memory records.")
    parser.add_argument("--repo-path", required=True, help="Path to a local git repository.")
    parser.add_argument("--name", help="Optional logical source name.")
    parser.add_argument("--commit-limit", type=int, default=100, help="Maximum number of recent commits to export.")
    parser.add_argument(
        "--doc-pattern",
        action="append",
        default=["README*", "*.md", "docs/**"],
        help="Git ls-files pattern for repo documents to include.",
    )
    parser.add_argument("--output", help="Optional output file path.")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    source_name = f"git:{args.name or repo_path.name}"
    records = build_commit_records(repo_path, source_name, args.commit_limit)
    records.extend(build_doc_records(repo_path, source_name, args.doc_pattern))

    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"{source_name.replace(':', '_')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"records": records}, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "records": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
