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

from .stamps import new_ulid


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


_NDJSON_CONTENT_TYPE = "application/x-ndjson"


class GcsBackend:
    """Store a jsonl log as one GCS object per name, appended via GCS compose.

    Each :meth:`append` uploads the new line to a per-append temp object and
    then composes ``[target, temp] → target`` server-side, so the target
    grows by one row without ever downloading its current contents.
    True O(1) per append against the network, matching the local jsonl
    contract.

    Every ``consolidate_every`` appends against a single target (counted
    per-process — the counter resets on restart), the target is rewritten
    as a fresh flat blob. This resets its ``componentCount`` so the object
    stays well clear of GCS's per-object component cap. Consolidation is
    an amortized O(N) event on the write path; the default keeps it rare.

    ``google-cloud-storage`` is imported lazily on first use — importing
    this module never requires the library. Install with
    ``pip install jsonl-log[gcs]`` to get the dependency.

    Single-writer per (bucket, prefix, name) tuple is assumed. Concurrent
    writers can race the ``target.exists()`` check on the first append and
    can interleave temp-object composes; see ``docs/v0.2-plan.md`` for the
    v0.3 candidates that fix this.
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

    def _object_name(self, name: str) -> str:
        return f"{self._prefix}{name}"

    def read_all(self, name: str) -> str | None:
        """Return the full contents of the composed target object, or None if absent."""
        blob = self._bucket().blob(self._object_name(name))
        if not blob.exists():
            return None
        return blob.download_as_text()

    def append(self, name: str, line: str) -> None:
        """Append ``line`` to the target object via GCS compose.

        First-time write: uploads ``line`` directly to the target — no
        compose needed. Subsequent writes: upload to a temp object,
        compose ``[target, temp] → target``, delete temp. Every
        ``consolidate_every`` appends, rewrite the target as a fresh flat
        blob to reset its component count.
        """
        target_name = self._object_name(name)
        bucket = self._bucket()
        target = bucket.blob(target_name)

        if not target.exists():
            # First append for this name in this bucket — no target to
            # compose onto. Upload the line directly and count it as one
            # component; consolidation will still trigger later.
            target.upload_from_string(line, content_type=_NDJSON_CONTENT_TYPE)
        else:
            # Compose path: upload the new line to a per-append temp object,
            # server-side-concat [target, temp] into target, then clean up
            # the temp. Temp names include a ULID so concurrent appends on
            # the same target don't collide on temp keys.
            temp_name = f"{target_name}.tmp.{new_ulid()}"
            temp = bucket.blob(temp_name)
            temp.upload_from_string(line, content_type=_NDJSON_CONTENT_TYPE)
            target.compose([target, temp])
            temp.delete()

        count = self._append_counts.get(target_name, 0) + 1
        if count >= self._consolidate_every:
            self._consolidate(target)
            count = 0
        self._append_counts[target_name] = count

    def _consolidate(self, target) -> None:
        """Rewrite ``target`` as a fresh flat blob to reset its componentCount.

        Download-then-upload keeps the semantics obvious and portable across
        google-cloud-storage versions. It is O(N) in the target's current
        size — a periodic latency spike on the write path, not a per-row
        cost. Called from :meth:`append` when the per-process counter hits
        ``consolidate_every``.
        """
        content = target.download_as_text()
        target.upload_from_string(content, content_type=_NDJSON_CONTENT_TYPE)
