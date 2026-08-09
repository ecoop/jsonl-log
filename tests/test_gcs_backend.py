# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for GcsBackend against a fake google.cloud.storage client (v0.2 planning skeleton).

Follows llm-cost-governor's pattern: monkeypatch `GcsBackend._client` with a
fake before any read/append so the lazy import never fires. See
docs/v0.2-plan.md §Test plan → test_gcs_backend.py.

All tests skip until v0.2 lands. No google-cloud-storage dependency needed.
"""

from __future__ import annotations

import pytest

_PLANNING_SKIP = "v0.2 planning skeleton — implement per docs/v0.2-plan.md"


def test_gcs_client_is_lazy():
    """Constructing GcsBackend(...) does not import google.cloud.storage (check sys.modules)."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_read_missing_returns_none():
    """No object exists at name → read_all returns None."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_read_returns_composed_content():
    """Object exists → read_all returns its text (including trailing newlines)."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_append_first_time_creates_target():
    """No prior object → target now contains `line`."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_append_subsequent_composes():
    """Target exists → append does upload(temp) + compose([target, temp], target) + delete(temp)."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_append_temp_object_is_deleted_after_compose():
    """After successful compose, no `.tmp.*` objects remain in the fake store."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_append_prefix_is_prepended_to_object_name():
    """GcsBackend(bucket, prefix='logs/') → append('feedback.jsonl', ...) targets 'logs/feedback.jsonl'."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_consolidation_triggers_at_threshold():
    """consolidate_every=3 → the 3rd append triggers a rewrite; contents unchanged, counter resets."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_consolidation_does_not_trigger_below_threshold():
    """consolidate_every=3, 2 appends → no rewrite call observed."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_append_content_type_is_ndjson():
    """Temp object upload uses application/x-ndjson (see open question #2 for confirmation)."""
    pytest.skip(_PLANNING_SKIP)
