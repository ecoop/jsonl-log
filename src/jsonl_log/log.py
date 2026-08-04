# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Append-only JSONL log: atomic append + last-row-wins reads.

The write path (`append_jsonl`) and the read helpers (`read_all`,
`read_latest`, `read_latest_list`) are the storage-agnostic core — the exact
shape three separate codebases had reimplemented. The `JsonlLog` class binds a
path + lock + optional auto-stamping for the richer, id-minting flavour.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from .stamps import new_ulid, utc_now_iso

Row = dict[str, Any]
Where = Callable[[Row], bool]

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
    ) -> None:
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

    def append(self, record: Row) -> str | None:
        """Stamp (per config) and append one record.

        Returns the row's id when ``stamp_id`` is on — minting a fresh ULID
        when the caller didn't supply one — else ``None``. Callers use the
        returned id as a back-reference (pitchcraft records a decision's ULID
        on the constraint it emits).
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
        append_jsonl(self.path, row, lock=self._lock)
        return row_id

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
