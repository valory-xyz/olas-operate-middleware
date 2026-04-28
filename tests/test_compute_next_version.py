# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------
"""Unit tests for scripts/compute_next_version.py."""

import pytest

from scripts.compute_next_version import (
    FALLBACK_REPO,
    FEAT_PREFIX,
    PullRequest,
    bump_version,
    determine_bump,
    parse_version,
    resolve_repo,
    tag_to_version,
)

pytestmark = pytest.mark.unit


class TestParseVersion:
    """Tests for parse_version."""

    def test_basic(self) -> None:
        """A simple major.minor.patch parses correctly."""
        assert parse_version("0.15.11") == (0, 15, 11)

    def test_zero(self) -> None:
        """All-zero version parses correctly."""
        assert parse_version("0.0.0") == (0, 0, 0)

    @pytest.mark.parametrize(
        "bad",
        ["0.15", "0.15.11.1", "1.2.x", "v1.2.3", ""],
    )
    def test_rejects_bad_format(self, bad: str) -> None:
        """Inputs that are not strict MAJOR.MINOR.PATCH are rejected."""
        with pytest.raises(ValueError, match="expected MAJOR"):
            parse_version(bad)


class TestTagToVersion:
    """Tests for tag_to_version."""

    def test_strips_v_prefix(self) -> None:
        """A leading 'v' on the tag is stripped."""
        assert tag_to_version("v0.15.11") == "0.15.11"

    def test_passes_through_when_no_prefix(self) -> None:
        """A tag without a leading 'v' is returned unchanged."""
        assert tag_to_version("0.15.11") == "0.15.11"


class TestBumpVersion:
    """Tests for bump_version."""

    @pytest.mark.parametrize(
        ("current", "bump_type", "expected"),
        [
            ((0, 15, 11), "patch", (0, 15, 12)),
            ((0, 15, 11), "minor", (0, 16, 0)),
            ((0, 15, 11), "major", (1, 0, 0)),
            ((1, 2, 3), "major", (2, 0, 0)),
            ((0, 0, 0), "minor", (0, 1, 0)),
        ],
    )
    def test_bumps(
        self,
        current: tuple[int, int, int],
        bump_type: str,
        expected: tuple[int, int, int],
    ) -> None:
        """Each bump kind produces the expected next version."""
        assert bump_version(current, bump_type) == expected

    def test_unknown_type_raises(self) -> None:
        """Unrecognised bump types raise ValueError."""
        with pytest.raises(ValueError, match="unknown bump type"):
            bump_version((1, 0, 0), "unknown")


class TestFeatPrefixRegex:
    """Tests for the FEAT_PREFIX regex matching conventional-commit feat titles."""

    @pytest.mark.parametrize(
        "title",
        [
            "feat: add foo",
            "feat(scope): add foo",
            "feat!: breaking",
            "feat(scope)!: breaking",
            "FEAT: shouty",
            "Feat(api): mixed case",
        ],
    )
    def test_matches(self, title: str) -> None:
        """Recognised feat-prefixed titles match."""
        assert FEAT_PREFIX.match(title) is not None

    @pytest.mark.parametrize(
        "title",
        [
            "fix: bug",
            "feature: not conventional",
            "featuring: not feat",
            "chore: cleanup",
            "Add feat to thing",
            "",
        ],
    )
    def test_does_not_match(self, title: str) -> None:
        """Unrelated titles do not match the feat prefix."""
        assert FEAT_PREFIX.match(title) is None


class TestDetermineBump:
    """Tests for determine_bump."""

    def test_empty_defaults_to_patch(self) -> None:
        """An empty PR list resolves to patch."""
        assert determine_bump([]) == "patch"

    def test_breaking_change_label_wins(self) -> None:
        """A breaking-change label beats a feat prefix."""
        prs = [
            PullRequest(1, "feat: add foo", ("breaking change",)),
            PullRequest(2, "fix: bug", ()),
        ]
        assert determine_bump(prs) == "major"

    def test_breaking_label_on_any_pr_triggers_major(self) -> None:
        """A breaking-change label on any PR in the set triggers major."""
        prs = [
            PullRequest(1, "fix: bug", ()),
            PullRequest(2, "chore: cleanup", ("breaking change",)),
            PullRequest(3, "fix: another", ()),
        ]
        assert determine_bump(prs) == "major"

    def test_feat_prefix_triggers_minor(self) -> None:
        """A feat-prefixed PR title triggers minor."""
        prs = [
            PullRequest(1, "feat: add foo", ()),
            PullRequest(2, "fix: bug", ()),
        ]
        assert determine_bump(prs) == "minor"

    def test_no_feat_no_breaking_is_patch(self) -> None:
        """Without breaking label or feat prefix, the bump is patch."""
        prs = [
            PullRequest(1, "fix: bug", ()),
            PullRequest(2, "chore: cleanup", ()),
            PullRequest(3, "Plain English title", ("documentation",)),
        ]
        assert determine_bump(prs) == "patch"

    def test_label_match_is_exact(self) -> None:
        """Label matching is exact: breaking-change with hyphen does not trigger major."""
        prs = [PullRequest(1, "fix: bug", ("breaking-change",))]
        assert determine_bump(prs) == "patch"

    def test_unrelated_labels_ignored(self) -> None:
        """Labels other than breaking-change do not influence the bump."""
        prs = [
            PullRequest(1, "fix: bug", ("agent-review", "python", "documentation")),
        ]
        assert determine_bump(prs) == "patch"


class TestResolveRepo:
    """Tests for resolve_repo."""

    def test_uses_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When GITHUB_REPOSITORY is set, it is returned."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        assert resolve_repo() == "owner/repo"

    def test_falls_back_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When GITHUB_REPOSITORY is unset, the fallback constant is returned."""
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        assert resolve_repo() == FALLBACK_REPO


class TestPullRequestBranch:
    """Tests for the PullRequest.branch field."""

    def test_branch_field_defaults_to_empty(self) -> None:
        """The branch field defaults to an empty string."""
        pr = PullRequest(number=1, title="fix: bug", labels=())
        assert pr.branch == ""

    def test_branch_field_set_explicitly(self) -> None:
        """The branch field stores the value passed at construction time."""
        pr = PullRequest(number=1, title="feat: x", labels=(), branch="feature/foo")
        assert pr.branch == "feature/foo"
