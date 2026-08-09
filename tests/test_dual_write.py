# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for JsonlLog dual-write behavior with a durable backend (v0.2 planning skeleton).

Uses a FakeDurableBackend (defined per test or in conftest.py by the
implementation session). No google-cloud-storage dependency. See
docs/v0.2-plan.md §Test plan → test_dual_write.py.

All tests skip until v0.2 lands.
"""

from __future__ import annotations

import pytest

_PLANNING_SKIP = "v0.2 planning skeleton — implement per docs/v0.2-plan.md"


def test_no_backend_is_unchanged(tmp_path):
    """durable_backend=None behaves byte-for-byte like today; existing tests still pass."""
    pytest.skip(_PLANNING_SKIP)


def test_append_writes_local_and_backend(tmp_path):
    """One append → one local line AND one backend.append(name, line) with matching content."""
    pytest.skip(_PLANNING_SKIP)


def test_default_durable_name_is_path_basename(tmp_path):
    """JsonlLog('data/feedback.jsonl') → backend.append('feedback.jsonl', ...)."""
    pytest.skip(_PLANNING_SKIP)


def test_explicit_durable_name_overrides_default(tmp_path):
    """durable_name='override.jsonl' wins over Path(path).name."""
    pytest.skip(_PLANNING_SKIP)


def test_backend_failure_soft_by_default(tmp_path, caplog):
    """strict=False → row on local disk, warning logged, append() returns normally."""
    pytest.skip(_PLANNING_SKIP)


def test_backend_failure_strict_raises(tmp_path):
    """strict=True → exception propagates; row IS still on local disk (documented)."""
    pytest.skip(_PLANNING_SKIP)


def test_read_helpers_are_local_only(tmp_path):
    """read_all / read_latest / read_latest_list never call the backend."""
    pytest.skip(_PLANNING_SKIP)


def test_one_backend_serves_multiple_logs(tmp_path):
    """A single GcsBackend instance can back N JsonlLogs with distinct durable_names."""
    pytest.skip(_PLANNING_SKIP)
