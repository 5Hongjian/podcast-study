#!/usr/bin/env python3
"""Validate the public package; never read personal state outside the repository."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/podcast-study"


def main():
    errors = []
    root = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(root).resolve() != ROOT:
        raise SystemExit("Not an isolated repository")
    files = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "--cached", "--others",
                                     "--exclude-standard", "-z"]).decode().split("\0")
    files = sorted(set(filter(None, files)))
    allowed_roots = {".github", "docs", "scripts", "skills", "tests"}
    allowed_files = {".gitignore", "README.md", "AGENTS.md", "CHANGELOG.md", "VERSION"}
    disallowed_parts = {"runs", "state", "local", "backups", "sources", "podcast-work", ".env"}
    patterns = [
        r"/Users/[A-Za-z0-9_.-]+/", r"/home/[A-Za-z0-9_.-]+/",
        r"[A-Z]:\\Users\\[^\\\s]+\\",
        r"docs\.google\.com/(?:document|spreadsheets|presentation)/d/[A-Za-z0-9_-]+",
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
        r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
    ]
    for filename in files:
        path = ROOT / filename
        parts = Path(filename).parts
        if (parts[0] not in allowed_roots and filename not in allowed_files) or set(parts) & disallowed_parts:
            errors.append(f"Unexpected public path: {filename}")
        if path.is_symlink():
            errors.append(f"Symbolic link must not be published: {filename}")
            continue
        if not path.is_file():
            continue
        if path.suffix not in {".md", ".py", ".json", ".yaml", ".yml", ""} and filename != ".gitignore":
            errors.append(f"Unexpected file type: {filename}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"Non-text file: {filename}")
            continue
        for pattern in patterns:
            if re.search(pattern, content):
                errors.append(f"Potential private content: {filename}")
        if path.suffix == ".md":
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
                if "://" not in target and not target.startswith("#"):
                    resolved = (path.parent / target.split("#")[0]).resolve()
                    if not resolved.is_relative_to(ROOT) or not resolved.exists():
                        errors.append(f"Broken or external local link: {filename} -> {target}")
    version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append("VERSION must use X.Y.Z")
    skill_text = (SKILL / "SKILL.md").read_text()
    if not skill_text.startswith("---\n") or "\nname: podcast-study\n" not in skill_text:
        errors.append("Missing skill frontmatter/name")
    if f'version: "{version}"' not in skill_text.split("---")[1]:
        errors.append("Skill version differs from VERSION")
    run = json.loads((SKILL / "assets/run-template.json").read_text())
    if run["skill_version"] != version or f'workflow-version: "{run["workflow_version"]}"' not in skill_text:
        errors.append("Run template versions differ from skill")
    for key in ("run_id", "created_at", "updated_at", "working_dir", "last_error"):
        if run[key] is not None:
            errors.append(f"Run template contains populated {key}")
    for key in ("episode", "document"):
        if any(value is not None for value in run[key].values()):
            errors.append(f"Run template contains populated {key}")
    for key in ("files", "media_sources", "topic_index", "limitations"):
        if run[key]:
            errors.append(f"Run template contains populated {key}")
    if run["cleanup"] != {"eligible": False, "status": "not_started", "receipts": []}:
        errors.append("Run template contains cleanup authorization/results")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(files)} public files; version {version}; template empty; local links intact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
