#!/usr/bin/env python3
"""Install/update the portable skill without overwriting user state. Python 3.10+."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "podcast-study"


def inside(path, parent):
    return path == parent or parent in path.parents


def fingerprint(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if "__pycache__" in path.relative_to(directory).parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError("Skill contents must not contain symbolic links")
        if path.is_file():
            result[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def install(source, destination, state):
    source = Path(source).resolve()
    destination = Path(destination).expanduser().resolve()
    state = Path(state).expanduser().resolve()
    if not (source / "SKILL.md").is_file():
        raise ValueError("Source has no SKILL.md")
    if inside(state, ROOT) or inside(destination, ROOT):
        raise ValueError("Install destination and personal state must be outside the repository")
    if any((inside(state, destination), inside(destination, state),
            inside(source, destination), inside(destination, source))):
        raise ValueError("Skill, source, and personal state must not overlap")
    expected = fingerprint(source)
    existing = destination.exists()
    if existing:
        entry = destination / "SKILL.md"
        if not entry.is_file() or "name: podcast-study" not in entry.read_text(encoding="utf-8"):
            raise ValueError("Destination is not an existing podcast-study installation")
    changed = not existing or fingerprint(destination) != expected
    backup = None
    if changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".podcast-study-stage-", dir=destination.parent))
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            if fingerprint(staging) != expected:
                raise OSError("Staged copy did not match source")
            if existing:
                backup = state / "backups" / ("podcast-study-" + uuid.uuid4().hex)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(backup))
            try:
                os.replace(staging, destination)
            except Exception:
                if backup is not None:
                    shutil.move(str(backup), str(destination))
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    state.mkdir(parents=True, exist_ok=True)
    return {"changed": changed, "destination": str(destination), "state": str(state),
            "backup": str(backup) if backup else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".agents" / "skills")
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    parser.add_argument("--state-dir", type=Path,
                        default=Path(os.environ.get("PODCAST_STUDY_HOME", str(codex_home / "podcast-study"))))
    args = parser.parse_args()
    try:
        result = install(SOURCE, args.skills_dir / "podcast-study", args.state_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, "Installation stopped: " + str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Installed. Existing task records, source files, and other local state were preserved. Restart Codex if the skill does not appear.")


if __name__ == "__main__":
    main()
