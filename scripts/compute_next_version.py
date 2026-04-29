"""Compute the next release version based on PRs merged since the previous tag.

Bump rule:
  - any PR has label "breaking change" -> minor
  - else -> patch

(No major bumps: aligns with the open-autonomy convention.)

Outputs JSON to stdout for downstream consumption by the release workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable


BREAKING_LABEL = "breaking change"
FALLBACK_REPO = "valory-xyz/olas-operate-middleware"
PR_FETCH_LIMIT = 200


def resolve_repo() -> str:
    """$GITHUB_REPOSITORY (always set in CI), else local fallback."""
    return os.environ.get("GITHUB_REPOSITORY") or FALLBACK_REPO


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    labels: tuple[str, ...]
    branch: str = ""


def _run(cmd: list[str]) -> str:
    return subprocess.run(
        cmd, capture_output=True, text=True, check=True
    ).stdout.strip()


def latest_release_tag(repo: str) -> str:
    """Return the latest published release's tag, queried from GitHub.

    Using ``gh release list`` (rather than ``git describe --tags``) avoids the
    failure mode where the latest release tag is not reachable from the current
    branch's history — e.g. when the tag was created via the GitHub UI on a
    detached commit, or via a workflow that never pushed back to main.
    """
    raw = _run(
        [
            "gh", "release", "list",
            "--repo", repo,
            "--limit", "1",
            "--json", "tagName",
        ]
    )
    data = json.loads(raw)
    if not data:
        raise RuntimeError(f"No releases found on {repo}")
    return data[0]["tagName"]


def tag_commit_date(tag: str) -> str:
    return _run(["git", "log", "-1", "--format=%cI", tag])


def tag_to_version(tag: str) -> str:
    return tag.lstrip("v")


def parse_version(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"expected MAJOR.MINOR.PATCH, got {version!r}")
    major, minor, patch = (int(p) for p in parts)
    return major, minor, patch


def bump_version(version: tuple[int, int, int], bump_type: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if bump_type == "minor":
        return major, minor + 1, 0
    if bump_type == "patch":
        return major, minor, patch + 1
    raise ValueError(f"unknown bump type: {bump_type!r}")


def determine_bump(prs: Iterable[PullRequest]) -> str:
    if any(BREAKING_LABEL in pr.labels for pr in prs):
        return "minor"
    return "patch"


def fetch_merged_prs(since_iso: str, repo: str) -> list[PullRequest]:
    raw = _run([
        "gh", "pr", "list",
        "--repo", repo,
        "--state", "merged",
        "--base", "main",
        "--search", f"merged:>{since_iso}",
        "--limit", str(PR_FETCH_LIMIT),
        "--json", "number,title,labels,headRefName",
    ])
    data = json.loads(raw)
    return [
        PullRequest(
            number=item["number"],
            title=item["title"],
            labels=tuple(label["name"] for label in item["labels"]),
            branch=item["headRefName"],
        )
        for item in data
    ]


def compute(prev_tag: str, repo: str) -> dict:
    prev_version = tag_to_version(prev_tag)
    parsed = parse_version(prev_version)
    since = tag_commit_date(prev_tag)
    prs = fetch_merged_prs(since, repo)
    bump_type = determine_bump(prs)
    next_version = ".".join(str(x) for x in bump_version(parsed, bump_type))
    return {
        "previous_version": prev_version,
        "previous_tag": prev_tag,
        "next_version": next_version,
        "next_tag": f"v{next_version}",
        "bump_type": bump_type,
        "prs": [
            {
                "number": pr.number,
                "title": pr.title,
                "labels": list(pr.labels),
                "branch": pr.branch,
            }
            for pr in prs
        ],
        "branches": list(dict.fromkeys(pr.branch for pr in prs if pr.branch)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prev-tag",
        help="Previous git tag. Defaults to latest tag in the current repo.",
    )
    args = parser.parse_args(argv)

    repo = resolve_repo()
    prev_tag = args.prev_tag or latest_release_tag(repo)
    result = compute(prev_tag, repo)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
