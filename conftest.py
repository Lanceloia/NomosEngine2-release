"""Require named test modules and one local test process at a time."""

from __future__ import annotations

import fcntl
from pathlib import Path

import pytest

_LOCK = None


def pytest_configure(config):
    global _LOCK
    paths = [str(argument).split("::", 1)[0] for argument in config.args]
    if not paths or any(
        not Path(path).is_file()
        or not Path(path).name.startswith("test_")
        or Path(path).suffix != ".py"
        for path in paths
    ):
        raise pytest.UsageError("name specific test_*.py modules or nodeids, not test directories")
    handle = (Path(config.rootpath) / ".pytest-run.lock").open("a")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.close()
        raise pytest.UsageError("another pytest process owns this repository test gate") from error
    _LOCK = handle


def pytest_unconfigure(config):
    global _LOCK
    if _LOCK is not None:
        _LOCK.close()
        _LOCK = None
