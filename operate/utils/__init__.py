# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""Helper utilities."""

import asyncio
import inspect
import logging
import os
import platform
import shutil
import time
import typing as t
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from pathlib import Path

from operate.constants import DEFAULT_TIMEOUT
from operate.serialization import BigInt


logger = logging.getLogger(__name__)


def create_backup(path: Path) -> Path:
    """Creates a backup of the specified path.

    This function creates a backup of a file or directory by copying it and appending
    the current UNIX timestamp followed by the '.bak' suffix.
    """

    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")

    timestamp = int(time.time())
    backup_path = path.with_name(f"{path.name}.{timestamp}.bak")

    if path.is_dir():
        shutil.copytree(path, backup_path)
    else:
        shutil.copy2(path, backup_path)

    return backup_path


NestedDict = t.Union[int, t.Dict[str, "NestedDict"]]


def merge_sum_dicts(*dicts: t.Dict[str, NestedDict]) -> t.Dict[str, NestedDict]:
    """
    Merge a list of nested dicts by summing all innermost `int` values.

    Supports arbitrary depth; keys not in all dicts are still included.
    Missing values are treated as 0.
    All `dicts` must follow the same nesting structure.
    """

    result: t.Dict[str, NestedDict] = {}
    for d in dicts:
        for k, v in d.items():  # type: ignore
            if isinstance(v, dict):
                result[k] = merge_sum_dicts(result.get(k, {}), v)  # type: ignore
            elif isinstance(v, int):
                result[k] = result.get(k, 0) + v  # type: ignore
    return result


def subtract_dicts(
    a: t.Dict[str, NestedDict], b: t.Dict[str, NestedDict]
) -> t.Dict[str, NestedDict]:
    """
    Recursively subtract values in `b` from `a`. Negative results are upper bounded at 0.

    Supports arbitrary depth; keys not in all dicts are still included.
    Missing values are treated as 0.
    All `dicts` must follow the same nesting structure.
    """

    result: t.Dict[str, NestedDict] = {}
    for key in a.keys() | b.keys():  # type: ignore
        va = a.get(key)  # type: ignore
        vb = b.get(key)  # type: ignore
        if isinstance(va, dict) or isinstance(vb, dict):
            result[key] = subtract_dicts(
                va if isinstance(va, dict) else {}, vb if isinstance(vb, dict) else {}
            )
        else:
            result[key] = BigInt(max((va or 0) - (vb or 0), 0))  # type: ignore
    return result


def safe_file_operation(operation: t.Callable, *args: t.Any, **kwargs: t.Any) -> None:
    """Safely perform file operation with retries on Windows."""
    max_retries = 3 if platform.system() == "Windows" else 1

    for attempt in range(max_retries):
        try:
            operation(*args, **kwargs)
            return
        except (PermissionError, FileNotFoundError, OSError) as e:
            if attempt == max_retries - 1:
                raise e

            if platform.system() == "Windows":
                # On Windows, wait a bit and retry
                time.sleep(0.1)


def secure_copy_private_key(src: Path, dst: Path) -> None:
    """
    Securely copy a private key file with strict permissions (0o600).

    Args:
        src: Source file path
        dst: Destination file path
    """
    # First copy the file
    shutil.copy2(src, dst)

    # Set restrictive permissions (read/write only for owner)
    try:
        dst.chmod(0o600)
    except (PermissionError, OSError):
        # On Windows, chmod may not work as expected; we still try to set via os.chmod
        try:
            os.chmod(dst, 0o600)
        except (PermissionError, OSError):
            # Log warning but continue - file is copied
            import warnings

            warnings.warn(f"Cannot set permissions on {dst}, please secure manually")


def unrecoverable_delete(file_path: Path, passes: int = 3) -> None:
    """Delete a file unrecoverably."""
    if not file_path.exists():
        return

    if not file_path.is_file():
        raise ValueError(f"{file_path} is not a file")

    try:
        file_size = os.path.getsize(file_path)

        with open(file_path, "r+b") as f:
            for _ in range(passes):
                # Overwrite with random bytes
                f.seek(0)
                random_data = os.urandom(file_size)
                f.write(random_data)
                f.flush()  # Ensure data is written to disk

        # Finally, delete the file
        safe_file_operation(os.remove, file_path)
    except PermissionError:
        print(f"Permission denied to securely delete file '{file_path}'.")
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error during secure deletion of '{file_path}': {e}")


@contextmanager
def timing_context(label: str = "Block") -> t.Generator[None, None, None]:
    """Context manager for timing a code block."""
    start = time.perf_counter()
    try:
        yield
    finally:
        end = time.perf_counter()
        logger.debug(f"[{label}] Elapsed time: {end - start:.4f} seconds")


def concurrent_execute(
    *func_calls: t.Tuple[t.Callable, t.Tuple],
    ignore_exceptions: bool = False,
) -> t.List[t.Any]:
    """Execute callables concurrently.

    This is a synchronous convenience wrapper around `parallel_execute_async`.
    If called from within an active asyncio event loop, use
    `await parallel_execute_async(...)` instead.
    """

    async def _runner() -> t.List[t.Any]:
        return await concurrent_execute_async(
            *func_calls,
            ignore_exceptions=ignore_exceptions,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread.
        return asyncio.run(_runner())

    # Running inside an event loop thread.
    # We cannot call `asyncio.run` here, so offload to a background thread.
    # NOTE: this blocks the current thread until completion.
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, _runner())
        return future.result()


async def concurrent_execute_async(
    *func_calls: t.Tuple[t.Callable, t.Tuple],
    ignore_exceptions: bool = False,
) -> t.List[t.Any]:
    """Execute callables concurrently using asyncio.

    - Async callables are awaited directly.
    - Sync callables are executed via `asyncio.to_thread`.

    Results are returned in the same order as `funcs`/`args_list`.
    """

    async def _invoke(func: t.Callable, args: t.Tuple) -> t.Any:
        with timing_context(f"Executing {func.__name__}"):
            if inspect.iscoroutinefunction(func):
                return await t.cast(t.Awaitable[t.Any], func(*args))
            return await asyncio.to_thread(func, *args)

    results: t.List[t.Any] = [None] * len(func_calls)

    async def _invoke_indexed(
        idx: int, func: t.Callable, args: t.Tuple
    ) -> t.Tuple[int, t.Any]:
        try:
            return idx, await _invoke(func, args)
        except Exception as e:  # pylint: disable=broad-except
            return idx, e

    tasks: t.List[asyncio.Task] = [
        asyncio.create_task(_invoke_indexed(idx, func, args))
        for idx, (func, args) in enumerate(func_calls)
    ]

    try:
        for task in asyncio.as_completed(tasks, timeout=DEFAULT_TIMEOUT):
            idx, outcome = await task
            if isinstance(outcome, BaseException):
                if ignore_exceptions:
                    results[idx] = None
                else:
                    raise outcome
            else:
                results[idx] = outcome
    except asyncio.TimeoutError as e:
        raise FuturesTimeoutError() from e
    finally:
        # Ensure we don't leak pending tasks.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    return results
