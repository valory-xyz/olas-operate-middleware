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

"""Local Anvil forks of the mainnet chains, one Docker container per chain."""

import contextlib
import logging
import os
import shutil
import socket
import subprocess  # nosec B404
import tempfile
import threading
import time
import typing as t
import uuid
from pathlib import Path
from platform import system
from urllib.parse import urlsplit

import pytest
import requests

from operate.operate_types import Chain

ANVIL_IMAGE = Path(__file__).with_name("ANVIL_IMAGE").read_text("utf-8").strip()
START_TIMEOUT = 180
START_ATTEMPTS = 3

_LOGGER = logging.getLogger(__name__)


def upstream_env_var(chain: Chain) -> str:
    """Name of the env var holding the chain's upstream RPC."""
    return f"{chain.value.upper()}_RPC"


# No public-RPC fallback: a rate-limited fork fails in ways that look like Anvil.
UPSTREAM_RPCS = {
    chain: os.environ[upstream_env_var(chain)]
    for chain in Chain
    if chain != Chain.SOLANA and os.environ.get(upstream_env_var(chain))
}

# The container exits when Anvil does, and closing stdin stops Anvil, so a killed
# pytest process leaves no container behind. Background jobs read /dev/null unless
# stdin is passed explicitly, hence fd 3.
_ANVIL_COMMAND = (
    'anvil --host "$ANVIL_HOST" --port "$ANVIL_PORT" --fork-url "$FORK_URL" '
    "--no-rate-limit --quiet & anvil=$!; exec 3<&0; "
    "(cat <&3 >/dev/null; kill $anvil) & wait $anvil"
)


class AnvilExited(RuntimeError):
    """Anvil stopped before its fork answered."""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def json_rpc(url: str, method: str, *params: t.Any, timeout: int = 60) -> t.Any:
    """Call a JSON-RPC method and return its result."""
    response = requests.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)},
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise RuntimeError(f"{method} failed: {body['error']}")
    return body.get("result")


def redact(text: str, upstream: str) -> str:
    """Hide the upstream RPC URL, which may carry a key, in Anvil's output."""
    parts = urlsplit(upstream)
    secrets = {upstream, parts.netloc, parts.path.strip("/"), parts.query}
    secrets.update(parts.path.split("/"))
    secrets.update(part for pair in parts.query.split("&") for part in pair.split("="))
    for secret in sorted(secrets, key=len, reverse=True):
        if len(secret) >= 8:
            text = text.replace(secret, "<upstream rpc>")
    return text


class AnvilFork:
    """An Anvil container forking one chain."""

    def __init__(self, chain: Chain, upstream: str) -> None:
        """Start the container and wait until the fork answers."""
        if shutil.which("docker") is None:
            raise RuntimeError(
                "Docker is required to run fork tests: Anvil runs from "
                f"{ANVIL_IMAGE}."
            )
        self.chain = chain
        self._upstream = upstream
        for attempt in range(START_ATTEMPTS):
            self._launch()
            try:
                self._wait_until_ready()
                return
            except BaseException as error:
                with contextlib.suppress(Exception):
                    self.stop()
                # The port is picked before Anvil binds it, so it can be taken.
                if isinstance(error, AnvilExited) and attempt + 1 < START_ATTEMPTS:
                    continue
                raise

    def _launch(self) -> None:
        self._name = f"operate-fork-{self.chain.value}-{uuid.uuid4().hex[:12]}"
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}"
        # Host networking where Docker supports it: no dependency on bridge NAT.
        if system() == "Linux":
            host, network = "127.0.0.1", ["--network", "host"]
        else:
            host = "0.0.0.0"  # nosec B104
            network = ["--publish", f"127.0.0.1:{port}:{port}"]
        self._output = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen(  # nosec B603, B607
                [
                    "docker",
                    "run",
                    "--rm",
                    "--interactive",
                    "--name",
                    self._name,
                    "--label",
                    "operate-test-fork",
                    *network,
                    "--env",
                    "FORK_URL",
                    "--env",
                    f"ANVIL_HOST={host}",
                    "--env",
                    f"ANVIL_PORT={port}",
                    "--entrypoint",
                    "sh",
                    ANVIL_IMAGE,
                    "-c",
                    _ANVIL_COMMAND,
                ],
                stdin=subprocess.PIPE,
                stdout=self._output,
                stderr=subprocess.STDOUT,
                env={**os.environ, "FORK_URL": self._upstream},
            )
        except BaseException:
            self._output.close()
            raise

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + START_TIMEOUT
        last_error: t.Optional[Exception] = None
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise AnvilExited(self._failure("exited"))
            try:
                chain_id = int(json_rpc(self.url, "eth_chainId", timeout=5), 16)
            except (
                requests.RequestException,
                RuntimeError,
                TypeError,
                ValueError,
            ) as e:
                last_error = e
                time.sleep(0.2)
                continue
            if chain_id != self.chain.id:
                raise RuntimeError(
                    f"The fork of {self.chain.value} serves chain id {chain_id}, "
                    f"expected {self.chain.id}: check its upstream RPC."
                )
            return
        raise RuntimeError(
            self._failure(f"did not start within {START_TIMEOUT}s")
            + f"\nlast readiness error: {redact(repr(last_error), self._upstream)}"
        )

    def _failure(self, what: str) -> str:
        self._output.seek(0)
        output = self._output.read().decode(errors="replace")
        return f"Anvil fork of {self.chain.value} {what}:\n" + redact(
            output, self._upstream
        )

    def refork(self) -> None:
        """Drop all state and fork again from the latest upstream block."""
        json_rpc(self.url, "anvil_reset", {"forking": {"jsonRpcUrl": self._upstream}})

    def stop(self) -> None:
        """Remove the container and its volumes."""
        removal = subprocess.run(  # nosec B603, B607
            ["docker", "rm", "--force", "--volumes", self._name],
            capture_output=True,
            text=True,
            check=False,
        )
        if removal.returncode and "No such container" not in removal.stderr:
            _LOGGER.warning(
                "docker rm %s exited with %s: %s",
                self._name,
                removal.returncode,
                removal.stderr.strip(),
            )
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
            try:
                self._process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                _LOGGER.warning("docker run %s did not exit; killing it", self._name)
                self._process.kill()
                self._process.wait()
        finally:
            self._output.close()


class AnvilForks:
    """Fork RPC URL per chain; a chain is forked the first time it is looked up."""

    def __init__(self) -> None:
        """Start with no forks."""
        self._forks: t.Dict[Chain, AnvilFork] = {}
        self._clean: t.Set[Chain] = set()
        self._lock = threading.Lock()

    def __getitem__(self, chain: Chain) -> str:
        """Fork RPC URL of the chain, with clean state for the current test."""
        if chain not in UPSTREAM_RPCS:
            if chain == Chain.SOLANA:
                raise KeyError(f"No fork is available for {chain.value}.")
            pytest.skip(
                f"{upstream_env_var(chain)} is not set, so {chain.value} cannot "
                "be forked."
            )
        with self._lock:
            if chain not in self._clean:
                self._forks[chain] = self._clean_fork(chain)
                self._clean.add(chain)
            return self._forks[chain].url

    def _clean_fork(self, chain: Chain) -> AnvilFork:
        fork = self._forks.get(chain)
        if fork is not None:
            try:
                fork.refork()
                return fork
            except (requests.RequestException, RuntimeError) as error:
                _LOGGER.warning(
                    "The fork of %s did not re-fork (%s); starting a new container",
                    chain.value,
                    redact(repr(error), UPSTREAM_RPCS[chain]),
                )
                with contextlib.suppress(Exception):
                    fork.stop()
        return AnvilFork(chain, UPSTREAM_RPCS[chain])

    def peek(self, chain: Chain) -> str:
        """Fork RPC URL of the chain, or an unreachable one if it is not forked."""
        with self._lock:
            if chain in self._clean:
                return self._forks[chain].url
        return f"http://unforked-{chain.value}.invalid"

    def isolate(self) -> None:
        """Give the next test clean state on every chain it looks up."""
        # Re-forking instead of evm_revert: non-archive upstreams prune the state
        # of a fork block within minutes.
        with self._lock:
            self._clean.clear()

    def stop(self) -> None:
        """Remove every container."""
        errors: t.List[Exception] = []
        with self._lock:
            for fork in self._forks.values():
                try:
                    fork.stop()
                except Exception as error:  # pylint: disable=broad-except
                    errors.append(error)
            self._forks.clear()
            self._clean.clear()
        if errors:
            raise RuntimeError(
                "; ".join(f"{type(e).__name__}: {e}" for e in errors)
            ) from errors[0]
