# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Real-GCS integration tests for the durable backend (v0.2 planning skeleton).

Gated on GCS_TEST_BUCKET. CI never runs this suite by default; local dev sets
GCS_TEST_BUCKET=<your-personal-bucket> to exercise the real compose/consolidate
paths. Each test picks a per-run ULID prefix and cleans up in a finalizer so
successive runs don't accumulate junk objects. See docs/v0.2-plan.md §Test
plan → test_gcs_integration.py.

All tests skip until v0.2 lands (and, thereafter, whenever GCS_TEST_BUCKET
is unset).
"""

from __future__ import annotations

import os

import pytest

_PLANNING_SKIP = "v0.2 planning skeleton — implement per docs/v0.2-plan.md"
_NO_BUCKET_SKIP = "set GCS_TEST_BUCKET=<bucket> to enable real-GCS integration tests"

pytestmark = pytest.mark.skipif(
    not os.getenv("GCS_TEST_BUCKET"),
    reason=_NO_BUCKET_SKIP,
)


def test_real_gcs_roundtrip():
    """Five appends via GcsBackend → read_all returns all five, in order."""
    pytest.skip(_PLANNING_SKIP)


def test_real_gcs_hydrate_after_restart():
    """Write via one JsonlLog; discard local; fresh JsonlLog + hydrate() → same rows."""
    pytest.skip(_PLANNING_SKIP)


def test_real_gcs_consolidation_end_to_end():
    """Enough appends to trigger one consolidation; read_all post-consolidation still matches."""
    pytest.skip(_PLANNING_SKIP)
