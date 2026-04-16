#!/usr/bin/env python3
"""Advise running middleware review before generic git commit Bash commands."""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict

COMMIT_COMMAND_PATTERN = re.compile(r"(^|[;&|()\s])git\b[^\n]*\bcommit\b")

ADVISORY_MESSAGE: Dict[str, Any] = {
    "systemMessage": (
        "Before committing, run the middleware-code-review skill and complete its "
        "strict pre-commit checklist."
    )
}


def main() -> int:
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")

    if not isinstance(command, str):
        return 0

    if COMMIT_COMMAND_PATTERN.search(command) is None:
        return 0

    print(json.dumps(ADVISORY_MESSAGE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
