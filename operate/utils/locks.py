#!/usr/bin/env python3
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

"""Locking helpers."""

import threading
import typing as t

Key = t.TypeVar("Key", bound=t.Hashable)


class KeyedLocks(t.Generic[Key]):
    """Lazily created locks, one per key.

    Serialises work per subject (a service, a chain, a pair of both) without
    serialising unrelated subjects against each other.
    """

    def __init__(self) -> None:
        """Initialize the keyed locks."""
        self._mutex = threading.Lock()
        self._locks: t.Dict[Key, threading.Lock] = {}

    def get(self, key: Key) -> threading.Lock:
        """Return the lock for a key, creating it on first use."""
        with self._mutex:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]
