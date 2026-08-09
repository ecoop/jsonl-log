# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for JsonlLog.hydrate() and JsonlLog.bootstrap() (v0.2 planning skeleton).

Covers startup-time GCS→local restore and the one-time local→GCS push for
consumers adopting durability on a pre-existing log. See docs/v0.2-plan.md
§Test plan → test_hydrate.py.

All tests skip until v0.2 lands.
"""

from __future__ import annotations

import pytest

_PLANNING_SKIP = "v0.2 planning skeleton — implement per docs/v0.2-plan.md"


# ── hydrate() ─────────────────────────────────────────────────────────────────

def test_hydrate_no_backend_is_noop(tmp_path):
    """durable_backend=None → hydrate() is a no-op, local file untouched."""
    pytest.skip(_PLANNING_SKIP)


def test_hydrate_populates_empty_local_from_backend(tmp_path):
    """Backend has content, local absent → after hydrate, local byte-matches backend."""
    pytest.skip(_PLANNING_SKIP)


def test_hydrate_overwrites_diverged_local(tmp_path, caplog):
    """Both sides have different content → GCS wins, warning logged about discarded local."""
    pytest.skip(_PLANNING_SKIP)


def test_hydrate_empty_backend_leaves_local_alone(tmp_path):
    """Backend has no object, local has rows → hydrate is no-op, local preserved."""
    pytest.skip(_PLANNING_SKIP)


def test_hydrate_is_atomic_on_local_side(tmp_path, monkeypatch):
    """Simulated mid-hydrate failure never leaves a truncated local file (temp + rename)."""
    pytest.skip(_PLANNING_SKIP)


def test_hydrate_after_local_appends_warns_or_refuses(tmp_path):
    """Consumer bug guard: hydrate() after appends should warn/refuse per open question #5."""
    pytest.skip(_PLANNING_SKIP)


# ── bootstrap() ───────────────────────────────────────────────────────────────

def test_bootstrap_pushes_local_when_backend_empty(tmp_path):
    """Local has rows, backend empty → after bootstrap, backend byte-matches local."""
    pytest.skip(_PLANNING_SKIP)


def test_bootstrap_noop_when_backend_has_content(tmp_path):
    """Backend non-empty → bootstrap does nothing (idempotent)."""
    pytest.skip(_PLANNING_SKIP)


def test_bootstrap_no_backend_is_noop(tmp_path):
    """durable_backend=None → bootstrap() is a no-op."""
    pytest.skip(_PLANNING_SKIP)


def test_hydrate_after_bootstrap_is_noop(tmp_path):
    """bootstrap() then hydrate() should be internally consistent (backend now non-empty)."""
    pytest.skip(_PLANNING_SKIP)
