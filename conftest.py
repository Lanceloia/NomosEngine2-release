"""Repository-wide pytest scope guard.

NomosEngine2 tests encode several distinct evidence layers.  Every invocation
must name its concrete test modules so a convenient directory or default-suite
command cannot silently turn a focused check into a costly broad run.
"""

from __future__ import annotations

import fcntl
import os
import secrets
from pathlib import Path

import pytest

SCOPE_ERROR = (
    "NomosEngine2 pytest requires explicit test modules; name one or more "
    "test_*.py paths (optionally with ::nodeid), not a directory or the default suite"
)
LOCK_ERROR = (
    "another NomosEngine2 pytest invocation is active; wait for it to finish "
    "instead of running test gates concurrently"
)
LOCK_TOKEN_ENV = "NE2_PYTEST_LOCK_TOKEN"


def _git_common_dir(marker: Path | None = None) -> Path:
    marker = marker if marker is not None else Path(__file__).resolve().parent / ".git"
    if marker.is_dir() or not marker.exists():
        return marker
    gitdir_line = marker.read_text(encoding="ascii").strip()
    if not gitdir_line.startswith("gitdir: "):
        raise pytest.UsageError("worktree Git control file is malformed")
    gitdir = (marker.parent / gitdir_line.removeprefix("gitdir: ")).resolve()
    common = gitdir / "commondir"
    return (gitdir / common.read_text(encoding="ascii").strip()).resolve()


LOCK_PATH = _git_common_dir() / "ne2-test-gates" / "pytest.lock"


def _is_explicit_test_module(target: object) -> bool:
    if type(target) is not str:
        return False
    path = target.split("::", 1)[0]
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.startswith("test_") and name.endswith(".py")


def _acquire_pytest_lock(config: pytest.Config) -> None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+", encoding="ascii")
    inherited_token = os.environ.get(LOCK_TOKEN_ENV)
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        owner_token = handle.read().strip()
        handle.close()
        if inherited_token and owner_token and secrets.compare_digest(inherited_token, owner_token):
            # Repository guard tests launch nested collection subprocesses. They
            # inherit the owning process token and are the only reentrant case.
            return
        raise pytest.UsageError(LOCK_ERROR) from None

    token = secrets.token_hex(32)
    handle.seek(0)
    handle.truncate()
    handle.write(token)
    handle.flush()
    os.environ[LOCK_TOKEN_ENV] = token
    config._ne2_pytest_lock_handle = handle  # type: ignore[attr-defined]
    config._ne2_pytest_lock_token = token  # type: ignore[attr-defined]


def pytest_configure(config: pytest.Config) -> None:
    targets = tuple(config.args)
    if not targets or not all(_is_explicit_test_module(target) for target in targets):
        raise pytest.UsageError(SCOPE_ERROR)
    _acquire_pytest_lock(config)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow-replays",
        action="store_true",
        help="Include marked world replays; explicit ::nodeid requests also opt in",
    )


def _explicitly_requested(item: pytest.Item, targets: tuple[str, ...]) -> bool:
    actual = item.nodeid.partition("::")[2]
    for target in targets:
        path, separator, requested = target.partition("::")
        if separator and Path(path).resolve() == item.path.resolve():
            if (
                actual == requested
                or actual.startswith(requested + "[")
                or actual.startswith(requested + "::")
            ):
                return True
    return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.option.collectonly or config.getoption("--run-slow-replays"):
        return
    retained, excluded = [], []
    for item in items:
        if item.get_closest_marker("slow_replay") and not _explicitly_requested(
            item, tuple(config.args)
        ):
            excluded.append(item)
        else:
            retained.append(item)
    if excluded:
        items[:] = retained
        config.hook.pytest_deselected(items=excluded)
        config._ne2_excluded_replays = tuple(item.nodeid for item in excluded)


def pytest_terminal_summary(terminalreporter, exitstatus, config: pytest.Config) -> None:
    excluded = getattr(config, "_ne2_excluded_replays", ())
    if excluded:
        terminalreporter.write_line(
            f"NE2: excluded {len(excluded)} slow replay(s); not executed or validated. "
            "Use --run-slow-replays or an explicit ::nodeid to run them."
        )


def pytest_unconfigure(config: pytest.Config) -> None:
    handle = getattr(config, "_ne2_pytest_lock_handle", None)
    token = getattr(config, "_ne2_pytest_lock_token", None)
    if handle is None:
        return
    if os.environ.get(LOCK_TOKEN_ENV) == token:
        os.environ.pop(LOCK_TOKEN_ENV, None)
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()
