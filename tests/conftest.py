# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Shared test fixtures.

The FakeDurableBackend defined here is the test double for
:class:`jsonl_log.DurableBackend`. It satisfies the Protocol duck-typed
(``isinstance(FakeDurableBackend(), DurableBackend)`` returns True), tracks
each ``append`` call for assertion, and exposes a ``fail_next`` flag so a
single call can be forced to raise — the shape needed for dual-write /
hydrate / bootstrap tests without importing ``google-cloud-storage``.
"""

from __future__ import annotations

import pytest


class FakeDurableBackend:
    """In-memory backend that satisfies :class:`jsonl_log.DurableBackend`.

    Attributes:
        store: {name: text} — mirrors the object store. ``read_all`` reads
            from here; ``append`` concatenates onto the entry.
        append_calls: list of ``(name, line)`` recorded on every ``append``
            for assertion. Populated even when ``fail_next`` fires (the call
            happened, even though its effect was rejected).
        fail_next: When True, the next ``append`` raises RuntimeError and
            resets to False. Used to test strict/soft failure semantics.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.append_calls: list[tuple[str, str]] = []
        self.fail_next: bool = False

    def read_all(self, name: str) -> str | None:
        return self.store.get(name)

    def append(self, name: str, line: str) -> None:
        self.append_calls.append((name, line))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated backend failure")
        self.store[name] = (self.store.get(name) or "") + line


@pytest.fixture
def fake_backend() -> FakeDurableBackend:
    """Fresh FakeDurableBackend per test."""
    return FakeDurableBackend()
