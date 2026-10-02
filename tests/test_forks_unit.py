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

"""Tests for the fork bookkeeping in tests/forks.py; no container is started."""

import typing as t
from unittest.mock import MagicMock, patch

import pytest

from operate.operate_types import Chain

from tests.forks import AnvilForks


def _fork(chain: Chain, _upstream: str) -> MagicMock:
    return MagicMock(url=f"http://fork-{chain.value}")


def _started(forks: AnvilForks, chain: Chain) -> MagicMock:
    return t.cast(MagicMock, forks._forks[chain])  # pylint: disable=protected-access


@pytest.fixture
def anvil_fork() -> t.Generator[MagicMock, None, None]:
    """Replace AnvilFork by a mock per started container."""
    with patch("tests.forks.AnvilFork", side_effect=_fork) as mock:
        yield mock


class TestAnvilForks:
    """Tests for AnvilForks."""

    def test_first_lookup_starts_one_fork(self, anvil_fork: MagicMock) -> None:
        """A chain is forked once per test, however often it is looked up."""
        forks = AnvilForks()

        assert forks[Chain.GNOSIS] == "http://fork-gnosis"
        assert forks[Chain.GNOSIS] == "http://fork-gnosis"

        assert anvil_fork.call_count == 1
        _started(forks, Chain.GNOSIS).refork.assert_not_called()

    def test_lookup_after_isolate_reforks(self, anvil_fork: MagicMock) -> None:
        """The next test reuses the container with fresh state."""
        forks = AnvilForks()
        url = forks[Chain.GNOSIS]
        fork = _started(forks, Chain.GNOSIS)

        forks.isolate()

        assert forks[Chain.GNOSIS] == url
        fork.refork.assert_called_once_with()
        assert anvil_fork.call_count == 1

    def test_failed_refork_replaces_the_fork(self, anvil_fork: MagicMock) -> None:
        """A container that no longer answers is removed and started again."""
        forks = AnvilForks()
        _ = forks[Chain.GNOSIS]
        dead = _started(forks, Chain.GNOSIS)
        dead.refork.side_effect = RuntimeError("connection refused")
        forks.isolate()

        assert forks[Chain.GNOSIS] == "http://fork-gnosis"

        dead.stop.assert_called_once_with()
        assert anvil_fork.call_count == 2
        assert _started(forks, Chain.GNOSIS) is not dead

    def test_peek_never_forks(self, anvil_fork: MagicMock) -> None:
        """Only a chain the current test looked up has a reachable URL."""
        forks = AnvilForks()
        unforked = "http://unforked-gnosis.invalid"

        assert forks.peek(Chain.GNOSIS) == unforked
        anvil_fork.assert_not_called()

        url = forks[Chain.GNOSIS]
        assert forks.peek(Chain.GNOSIS) == url

        forks.isolate()
        assert forks.peek(Chain.GNOSIS) == unforked

    def test_unsupported_chain_raises(self, anvil_fork: MagicMock) -> None:
        """A chain without an upstream is never forked."""
        with pytest.raises(KeyError, match="No fork is available for solana"):
            _ = AnvilForks()[Chain.SOLANA]
        anvil_fork.assert_not_called()

    def test_stop_removes_every_container(self, anvil_fork: MagicMock) -> None:
        """One container failing to stop does not leave the others running."""
        forks = AnvilForks()
        _ = forks[Chain.GNOSIS], forks[Chain.BASE]
        started = [_started(forks, Chain.GNOSIS), _started(forks, Chain.BASE)]
        started[0].stop.side_effect = RuntimeError("stuck")

        with pytest.raises(RuntimeError, match="stuck"):
            forks.stop()

        assert anvil_fork.call_count == 2
        for fork in started:
            fork.stop.assert_called_once_with()
        assert forks.peek(Chain.GNOSIS) == "http://unforked-gnosis.invalid"
