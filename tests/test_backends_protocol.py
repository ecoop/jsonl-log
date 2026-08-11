# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for the DurableBackend Protocol seam (v0.2 planning skeleton).

Covers the Protocol contract and its duck-typed acceptance of arbitrary
implementations. See docs/v0.2-plan.md §Test plan → test_backends_protocol.py.

All tests skip until v0.2 lands. This file exists so the implementation
session has concrete function names and one-line intent per test.
"""

from __future__ import annotations

import pytest

_PLANNING_SKIP = "v0.2 planning skeleton — implement per docs/v0.2-plan.md"


def test_fake_backend_satisfies_protocol():
    """An in-test class with read_all + append is accepted via runtime_checkable."""
    pytest.skip(_PLANNING_SKIP)


def test_gcs_backend_satisfies_protocol():
    """GcsBackend satisfies the Protocol without triggering the lazy google.cloud import."""
    pytest.skip(_PLANNING_SKIP)


def test_arbitrary_class_satisfies_protocol():
    """A future Firestore-shaped backend drops in with no inheritance."""
    pytest.skip(_PLANNING_SKIP)
