# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Append-only JSONL log: atomic append + last-row-wins reads.

The write path (`append_jsonl`) and the read helpers (`read_all`,
`read_latest`, `read_latest_list`) are the storage-agnostic core — the exact
shape three separate codebases had reimplemented. The `JsonlLog` class binds a
path + lock + optional auto-stamping for the richer, id-minting flavour.

v0.2 adds an optional ``durable_backend=`` to :class:`JsonlLog`: appends still
land on local disk first (unchanged read path), and are also mirrored into an
object-store backend so a container restart can rebuild local state via
:meth:`JsonlLog.hydrate`. Free functions are unchanged. See
``docs/v0.2-plan.md`` for the full contract.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from .backends import DurableBackend, DurableBackendError
from .stamps import new_ulid, utc_now_iso

Row = dict[str, Any]
Where = Callable[[Row], bool]

_logger = logging.getLogger("jsonl_log")

# Process-wide default write lock. Serializing appends stops concurrent writers
# from interleaving partial lines — JSONL requires exactly one complete object
# per line, and a raced write corrupts the file for every downstream reader.
#
# A single in-process lock is sufficient under a single-process server
# (uvicorn --reload, a CLI, a worker). A real multi-worker deployment needs
# OS-level file locking (fcntl.flock) or a dedicated append service; that's out
# of scope here. Callers with their own finer-grained lock pass it via `lock=`.
_DEFAULT_LOCK = Lock()


def append_jsonl(
    path: str | Path,
    record: Row,
    *,
    lock: Lock | None = None,
    ensure_ascii: bool = False,
) -> None:
    """Append one record as a single JSON line to ``path``.

    Creates parent directories as needed, serializes ``record`` to one line
    (``json.dumps(...) + "\\n"``), and appends it while holding a lock.

    Args:
        path: Target JSONL file.
        record: A JSON-serializable mapping.
        lock: Write lock to hold across the append. Defaults to a shared
            process-wide lock; pass your own for finer-grained control.
        ensure_ascii: Forwarded to :func:`json.dumps`. Defaults to False so
            non-ASCII text is written through as UTF-8 rather than escaped.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=ensure_ascii) + "\n"
    with (lock or _DEFAULT_LOCK), path.open("a", encoding="utf-8") as f:
        f.write(line)


def read_all(path: str | Path, *, where: Where | None = None) -> list[Row]:
    """Read every row from ``path`` in file order. Empty list if absent.

    Blank lines are skipped. ``where``, if given, keeps only rows for which it
    returns truthy.
    """
    path = Path(path)
    if not path.exists():
        return []
    rows: list[Row] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if where is None or where(row):
            rows.append(row)
    return rows


def read_latest(path: str | Path, key: str, *, where: Where | None = None) -> dict[Any, Row]:
    """Return ``{key_value: row}`` keeping the LAST row seen per key.

    The "last write wins" query: multiple rows may share a key (each append is
    its own event — a re-rating, a re-curated flag), and the final row for a
    key is its current state. Rows missing ``key`` are skipped. Empty dict if
    the file is absent.
    """
    latest: dict[Any, Row] = {}
    for row in read_all(path, where=where):
        if key in row:
            latest[row[key]] = row
    return latest


def read_latest_list(
    path: str | Path,
    key: str,
    *,
    where: Where | None = None,
    sort_desc: str | None = None,
) -> list[Row]:
    """Latest row per key as a list.

    With ``sort_desc`` (a field name, usually ``"timestamp"``) the result is
    sorted newest-first by that field; otherwise it preserves the order in
    which each key was last seen.
    """
    values = list(read_latest(path, key, where=where).values())
    if sort_desc is not None:
        values.sort(key=lambda r: r.get(sort_desc), reverse=True)
    return values


class JsonlLog:
    """A path-bound append-only JSONL log with optional auto-stamping.

    Wraps a single file with a write lock and the read helpers. When
    constructed with ``stamp_id`` / ``stamp_time`` / ``schema_version``, each
    appended record is stamped before it hits disk — the pitchcraft flavour,
    where every row carries a minted ULID ``id``, a UTC-ISO ``timestamp``, and
    a ``schema_version``.

    Field names are configurable so an existing record shape survives adoption
    unchanged: rulebook stamps a ``v`` version and no id; pitchcraft stamps
    ``schema_version`` + ``id``.

    Stamping never overwrites a field the caller already set, so you can:
      * pre-set ``timestamp`` to share one value across a batch (the pitchcraft
        da_notes case, where every note in a call gets the same stamp), or
      * pass an explicit ``id`` and have it preserved.

    Optionally accepts a ``durable_backend=`` for dual-write durability. When
    set, every :meth:`append` also mirrors the serialized line into the backend
    under the same lock as the local write. Reads stay local-only —
    :meth:`hydrate` (called once at startup) pulls the backend's state down
    into the local file so subsequent reads see it. Not passing a backend
    leaves every code path identical to v0.1 behavior.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        stamp_id: bool = False,
        stamp_time: bool = True,
        schema_version: int | str | None = None,
        id_field: str = "id",
        timestamp_field: str = "timestamp",
        version_field: str = "schema_version",
        timespec: str = "seconds",
        z: bool = True,
        lock: Lock | None = None,
        durable_backend: DurableBackend | None = None,
        durable_name: str | None = None,
        strict: bool = False,
    ) -> None:
        """Construct a path-bound log.

        Args new in v0.2:
            durable_backend: Optional :class:`DurableBackend`. When set, each
                :meth:`append` writes to local disk AND to the backend under
                the same lock. Default None preserves v0.1 behavior exactly.
            durable_name: Object name the backend uses for this log. Defaults
                to ``Path(path).name`` so ``JsonlLog("data/feedback.jsonl",
                durable_backend=...)`` stores as ``"feedback.jsonl"`` in the
                backend. Ignored when ``durable_backend`` is None.
            strict: When True, a backend failure on append raises
                :class:`DurableBackendError` (the local write has already
                committed and is NOT rolled back). When False (default) the
                same failure is logged as a warning and the append returns
                normally. Ignored when ``durable_backend`` is None.
        """
        self.path = Path(path)
        self.stamp_id = stamp_id
        self.stamp_time = stamp_time
        self.schema_version = schema_version
        self.id_field = id_field
        self.timestamp_field = timestamp_field
        self.version_field = version_field
        self.timespec = timespec
        self.z = z
        self._lock = lock or Lock()
        self._durable_backend = durable_backend
        self._durable_name = durable_name if durable_name is not None else self.path.name
        self._strict = strict
        # Guards hydrate() from silently overwriting rows appended after
        # startup. See :meth:`hydrate` docstring.
        self._appended_since_hydrate = False

    def append(self, record: Row) -> str | None:
        """Stamp (per config) and append one record.

        Returns the row's id when ``stamp_id`` is on — minting a fresh ULID
        when the caller didn't supply one — else ``None``. Callers use the
        returned id as a back-reference (pitchcraft records a decision's ULID
        on the constraint it emits).

        When a ``durable_backend`` is configured, the same serialized line is
        mirrored to the backend under the same lock as the local write. Local
        write always happens first; if the backend call fails and
        ``strict=False`` (default) the failure is logged and this method
        returns normally, with the row present on local disk but absent from
        the backend until a future append triggers backend consolidation.
        With ``strict=True`` the failure raises :class:`DurableBackendError`;
        the local write has already committed and is not rolled back.
        """
        row = dict(record)
        if self.stamp_time and self.timestamp_field not in row:
            row[self.timestamp_field] = utc_now_iso(timespec=self.timespec, z=self.z)
        if self.schema_version is not None and self.version_field not in row:
            row[self.version_field] = self.schema_version
        row_id: str | None = None
        if self.stamp_id:
            row_id = row.get(self.id_field) or new_ulid()
            row[self.id_field] = row_id

        line = json.dumps(row, ensure_ascii=False) + "\n"

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
            self._appended_since_hydrate = True

            if self._durable_backend is not None:
                try:
                    self._durable_backend.append(self._durable_name, line)
                except Exception as e:
                    if self._strict:
                        raise DurableBackendError(
                            f"durable backend append failed for {self._durable_name!r}"
                        ) from e
                    _logger.warning(
                        "durable backend append failed for %s: %s",
                        self._durable_name,
                        e,
                    )

        return row_id

    def hydrate(self, *, force: bool = False) -> None:
        """Populate local from ``durable_backend`` at startup.

        Contract:
          * No backend → no-op.
          * Backend has content → atomically overwrite local (write to a temp
            file, then :meth:`Path.replace`). GCS is authoritative; any local
            content that differs is discarded with a warning.
          * Backend is empty → local left untouched. See :meth:`bootstrap` for
            the one-time push-local-up case.

        MUST be called before any :meth:`append` calls when durability
        matters. If :meth:`append` has already happened this instance,
        ``hydrate()`` raises unless ``force=True`` — silently overwriting
        post-append rows is a data-loss footgun. Not thread-safe against
        concurrent writers on the log; call during startup, single-threaded.
        """
        if self._durable_backend is None:
            return

        if self._appended_since_hydrate and not force:
            raise RuntimeError(
                f"hydrate() called after append() on {self.path!s}; either call "
                "hydrate() at startup before any appends, or pass force=True "
                "to overwrite local with backend contents anyway."
            )

        with self._lock:
            remote_text = self._durable_backend.read_all(self._durable_name)

            if remote_text is None:
                _logger.info(
                    "hydrate: backend has no content for %s; local preserved",
                    self._durable_name,
                )
                return

            if self.path.exists():
                local_text = self.path.read_text(encoding="utf-8")
                if local_text != remote_text:
                    _logger.warning(
                        "hydrate: local content for %s differs from backend; "
                        "local discarded (backend is authoritative)",
                        self.path,
                    )

            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".hydrate.tmp")
            tmp.write_text(remote_text, encoding="utf-8")
            tmp.replace(self.path)
            self._appended_since_hydrate = False

    def bootstrap(self) -> None:
        """One-time: push local content up to ``durable_backend`` if it's empty.

        For consumers adopting durability on a pre-existing local log file.
        Idempotent when the backend already has content (no-op). No-op with
        no backend, and no-op when the local file doesn't exist. Not safe
        under concurrent writers; call during startup, single-threaded.

        A follow-up :meth:`hydrate` after ``bootstrap()`` is a no-op on the
        content (backend and local match) but resets the post-append guard.
        """
        if self._durable_backend is None:
            return

        remote_text = self._durable_backend.read_all(self._durable_name)
        if remote_text is not None:
            return  # backend already has content — nothing to bootstrap

        if not self.path.exists():
            return  # nothing local to push

        with self._lock:
            for line in self.path.read_text(encoding="utf-8").splitlines(keepends=True):
                if not line.strip():
                    continue
                # Preserve the trailing newline the Protocol requires; splitlines
                # with keepends returns lines exactly as they appear in the file,
                # so a final line without a trailing newline stays that way. Add
                # one if missing so the on-disk shape at the backend is uniform.
                if not line.endswith("\n"):
                    line = line + "\n"
                self._durable_backend.append(self._durable_name, line)

    def read_all(self, *, where: Where | None = None) -> list[Row]:
        """See :func:`read_all`, bound to this log's path."""
        return read_all(self.path, where=where)

    def read_latest(self, key: str, *, where: Where | None = None) -> dict[Any, Row]:
        """See :func:`read_latest`, bound to this log's path."""
        return read_latest(self.path, key, where=where)

    def read_latest_list(
        self,
        key: str,
        *,
        where: Where | None = None,
        sort_desc: str | None = None,
    ) -> list[Row]:
        """See :func:`read_latest_list`, bound to this log's path."""
        return read_latest_list(self.path, key, where=where, sort_desc=sort_desc)
