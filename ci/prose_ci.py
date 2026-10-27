"""Recognize the reviewed prose-only scope; all other changes need full CI."""

import os
import re
import subprocess
from pathlib import Path

PROSE_ROOTS = frozenset({"AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "README.md"})


def is_prose(path: str) -> bool:
    return path in PROSE_ROOTS or re.fullmatch(r"docs/adr/[^/\r\n]+\.md", path) is not None


def prose_only(paths: list[str]) -> bool:
    return bool(paths) and all(is_prose(path) for path in paths)


def changed_paths(base: str, head: str) -> list[str]:
    # No rename detection: both the removed source and added destination matter.
    result = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", base, head]
    )
    return [os.fsdecode(path) for path in result.split(b"\0") if path]


def main() -> None:
    # Tags and operational events keep their existing full checks.
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref = os.environ.get("GITHUB_REF", "")
    if event not in ("pull_request", "push") or ref.startswith("refs/tags/"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write("prose_only=false\n")
        print("Full CI required for this event")
        return
    base = os.environ["CI_PROSE_BASE"]
    head = os.environ["CI_PROSE_HEAD"]
    if not base or not head:
        raise SystemExit("Cannot classify CI scope without both revisions")
    if base == "0" * 40:
        base = (
            subprocess.check_output(["git", "hash-object", "-t", "tree", "--stdin"], input=b"")
            .decode()
            .strip()
        )
    paths = changed_paths(base, head)
    subprocess.run(["git", "diff", "--check", base, head], check=True)
    verdict = "true" if prose_only(paths) else "false"
    print(f"prose_only={verdict}; {len(paths)} changed paths")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"prose_only={verdict}\n")


if __name__ == "__main__":
    main()
