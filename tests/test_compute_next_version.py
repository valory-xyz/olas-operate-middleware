"""Unit tests for scripts/compute_next_version.py."""

import pytest

from scripts.compute_next_version import (
    FEAT_PREFIX,
    PullRequest,
    bump_version,
    determine_bump,
    parse_version,
    tag_to_version,
)


pytestmark = pytest.mark.unit


class TestParseVersion:
    def test_basic(self) -> None:
        assert parse_version("0.15.11") == (0, 15, 11)

    def test_zero(self) -> None:
        assert parse_version("0.0.0") == (0, 0, 0)

    @pytest.mark.parametrize("bad", ["0.15", "0.15.11.1", "1.2.x", "v1.2.3", ""])
    def test_rejects_bad_format(self, bad: str) -> None:
        with pytest.raises(ValueError):
            parse_version(bad)


class TestTagToVersion:
    def test_strips_v_prefix(self) -> None:
        assert tag_to_version("v0.15.11") == "0.15.11"

    def test_passes_through_when_no_prefix(self) -> None:
        assert tag_to_version("0.15.11") == "0.15.11"


class TestBumpVersion:
    @pytest.mark.parametrize(
        "current,bump_type,expected",
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
        assert bump_version(current, bump_type) == expected

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError):
            bump_version((1, 0, 0), "unknown")


class TestFeatPrefixRegex:
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
        assert FEAT_PREFIX.match(title) is None


class TestDetermineBump:
    def test_empty_defaults_to_patch(self) -> None:
        assert determine_bump([]) == "patch"

    def test_breaking_change_label_wins(self) -> None:
        prs = [
            PullRequest(1, "feat: add foo", ("breaking change",)),
            PullRequest(2, "fix: bug", ()),
        ]
        assert determine_bump(prs) == "major"

    def test_breaking_label_on_any_pr_triggers_major(self) -> None:
        prs = [
            PullRequest(1, "fix: bug", ()),
            PullRequest(2, "chore: cleanup", ("breaking change",)),
            PullRequest(3, "fix: another", ()),
        ]
        assert determine_bump(prs) == "major"

    def test_feat_prefix_triggers_minor(self) -> None:
        prs = [
            PullRequest(1, "feat: add foo", ()),
            PullRequest(2, "fix: bug", ()),
        ]
        assert determine_bump(prs) == "minor"

    def test_no_feat_no_breaking_is_patch(self) -> None:
        prs = [
            PullRequest(1, "fix: bug", ()),
            PullRequest(2, "chore: cleanup", ()),
            PullRequest(3, "Plain English title", ("documentation",)),
        ]
        assert determine_bump(prs) == "patch"

    def test_label_match_is_exact(self) -> None:
        # "breaking-change" with hyphen should NOT trigger major
        prs = [PullRequest(1, "fix: bug", ("breaking-change",))]
        assert determine_bump(prs) == "patch"

    def test_unrelated_labels_ignored(self) -> None:
        prs = [
            PullRequest(1, "fix: bug", ("agent-review", "python", "documentation")),
        ]
        assert determine_bump(prs) == "patch"
