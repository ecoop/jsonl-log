# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Durable backends for the jsonl log.

`JsonlLog` accepts an optional ``durable_backend=`` — a mirror of local disk
into an object store, so that the container-ephemeral local file is
reconstructible on restart via :meth:`JsonlLog.hydrate`.

Two shapes live here:

* :class:`DurableBackend` — the Protocol. ``read_all`` returns the whole
  object's text (or None if absent). ``append`` adds one already-serialized
  line. Backends own the append semantics of their medium — GCS uses
  compose+consolidate to preserve per-row O(1) writes; a future S3 backend
  might batch via multipart uploads. Callers see only read/append.
* :class:`GcsBackend` — concrete implementation for Google Cloud Storage.
  Filled in a separate PR; here as a stub whose methods raise
  ``NotImplementedError`` so ``__init__.py`` can already export it and so
  callers can wire the plumbing ahead of the compose/consolidate work.

The ``google-cloud-storage`` client is imported lazily on first use in
:class:`GcsBackend` so importing this module never requires the library —
only actually reading or appending to GCS does. Mirrors
``llm_cost_governor.state``'s pattern.

Errors from a real backend are wrapped in :class:`DurableBackendError` so
callers can ``except`` without importing google-cloud-storage themselves.
The original exception is chained via ``raise ... from`` so tracebacks
still point at the underlying cause.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class DurableBackendError(RuntimeError):
    """Raised when a durable backend operation fails.

    Wraps the underlying provider exception (chained via ``raise ... from``)
    so consumer ``except`` clauses stay backend-agnostic. In strict mode
    :meth:`JsonlLog.append` propagates this; in non-strict mode the same
    condition is logged as a warning and the exception is not raised.
    """


@runtime_checkable
class DurableBackend(Protocol):
    """Durable append-only object store for a jsonl log.

    Backends own the append semantics of their storage medium — GCS uses
    compose+consolidate to preserve per-row O(1) writes; a hypothetical S3
    backend might batch via multipart uploads. Callers see only read/append.

    The Protocol is ``runtime_checkable`` so tests and consumers can accept
    any duck-typed instance without importing this module for inheritance.
    """

    def read_all(self, name: str) -> str | None:
        """Return the full contents of ``name`` as text, or None if absent.

        Text includes the trailing newlines the backend saw on
        :meth:`append` — the return value round-trips into
        ``path.write_text(...)`` unchanged.
        """
        ...

    def append(self, name: str, line: str) -> None:
        """Append ``line`` (which must end in ``"\\n"``) to ``name``.

        Must be amortized O(1) per call. A return means the row is durable
        at the backend's freshness guarantee.
        """
        ...


class GcsBackend:
    """Store a jsonl log as one GCS object per name, appended via GCS compose.

    Stub in this PR — methods raise :class:`NotImplementedError`. The
    compose+consolidate body lands in a follow-up PR alongside the
    ``google-cloud-storage`` optional dependency and integration tests.

    The constructor is finalised now so wiring code (``JsonlLog(...,
    durable_backend=GcsBackend(...))``) can compile against the intended
    public shape.
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "",
        consolidate_every: int = 1000,
    ) -> None:
        """Configure a GCS-backed durable store.

        Args:
            bucket: GCS bucket name. Client picks up credentials via
                Application Default Credentials — no explicit auth here.
            prefix: Optional key prefix applied to every object name (e.g.
                ``"logs/"`` so a log named ``"feedback.jsonl"`` lives at
                ``"logs/feedback.jsonl"``). Trailing slash is caller-
                controlled; no normalization.
            consolidate_every: After this many appends against a single
                object (counted per-process, resetting on restart), rewrite
                the target as a flat blob to reset its ``componentCount``.
                Guards against the per-object component cap; not a
                read-performance knob.
        """
        self._bucket_name = bucket
        self._prefix = prefix
        self._consolidate_every = consolidate_every
        self._client = None  # lazy — see _bucket()
        self._append_counts: dict[str, int] = {}

    def _bucket(self):
        if self._client is None:
            from google.cloud import storage  # lazy: only when GCS is used

            self._client = storage.Client()
        return self._client.bucket(self._bucket_name)

    def read_all(self, name: str) -> str | None:
        raise NotImplementedError(
            "GcsBackend.read_all is a v0.2 stub; the compose/consolidate "
            "body lands in the next PR. See docs/v0.2-plan.md."
        )

    def append(self, name: str, line: str) -> None:
        raise NotImplementedError(
            "GcsBackend.append is a v0.2 stub; the compose/consolidate "
            "body lands in the next PR. See docs/v0.2-plan.md."
        )
