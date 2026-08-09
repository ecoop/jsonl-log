# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for the DurableBackend Protocol seam.

Covers the Protocol contract and its duck-typed acceptance of arbitrary
implementations. GcsBackend's own body lands in a later PR; here we only
prove the class *shape* satisfies the Protocol without triggering the lazy
google-cloud-storage import.
"""

from __future__ import annotations

import sys

from jsonl_log import DurableBackend, GcsBackend


def test_fake_backend_satisfies_protocol(fake_backend):
    # runtime_checkable → isinstance uses the Protocol's method names as the
    # duck-typing signature. If DurableBackend ever grows a method the fake
    # doesn't implement, this test flags it.
    assert isinstance(fake_backend, DurableBackend)


def test_gcs_backend_satisfies_protocol():
    # Constructing GcsBackend must not import google.cloud.storage (lazy).
    # If the import were eager, this test would drag it into every CI run.
    backend = GcsBackend("some-bucket")
    assert isinstance(backend, DurableBackend)
    assert "google.cloud.storage" not in sys.modules


def test_arbitrary_class_satisfies_protocol():
    """A future Firestore-shaped backend drops in with no inheritance."""

    class InMemoryBackend:
        def __init__(self) -> None:
            self._d: dict[str, str] = {}

        def read_all(self, name):
            return self._d.get(name)

        def append(self, name, line):
            self._d[name] = (self._d.get(name) or "") + line

    backend = InMemoryBackend()
    assert isinstance(backend, DurableBackend)
    backend.append("k", "hi\n")
    assert backend.read_all("k") == "hi\n"
