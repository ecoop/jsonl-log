# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""ULID + UTC-ISO timestamp helpers shared by every JSONL log.

These are the two stamps that appeared, identically or near-identically, in
every append-only log this package was extracted from. `utc_now_iso` defaults
to the pitchcraft flavour (`Z`-suffixed, second precision); pass `timespec=` /
`z=` for the rulebook flavour (`datetime.now(utc).isoformat()` — auto precision,
no suffix).
"""

from __future__ import annotations

from datetime import UTC, datetime

from ulid import ULID


def new_ulid() -> str:
    """Mint a fresh ULID as a string — lexicographically sortable, time-ordered."""
    return str(ULID())


def utc_now_iso(*, timespec: str = "seconds", z: bool = True) -> str:
    """Current UTC time as an ISO-8601 string.

    Defaults (``timespec="seconds", z=True``) produce a ``Z``-suffixed,
    second-precision stamp: ``2026-08-04T12:34:56Z`` — the pitchcraft flavour.

    Pass ``timespec="auto", z=False`` for the bare
    ``datetime.now(timezone.utc).isoformat()`` form used by rulebook:
    ``2026-08-04T12:34:56.789012+00:00``.

    Args:
        timespec: Forwarded to :meth:`datetime.isoformat` — one of
            ``"auto"``, ``"seconds"``, ``"milliseconds"``, ``"microseconds"``,
            etc.
        z: When True, replace the trailing ``+00:00`` offset with ``Z``.
    """
    stamp = datetime.now(UTC).isoformat(timespec=timespec)
    if z:
        stamp = stamp.replace("+00:00", "Z")
    return stamp
