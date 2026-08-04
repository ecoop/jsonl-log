# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for the ULID + UTC-ISO stamp helpers."""

from __future__ import annotations

import re

from jsonl_log import new_ulid, utc_now_iso


def test_new_ulid_is_26_char_string():
    ulid = new_ulid()
    assert isinstance(ulid, str)
    assert len(ulid) == 26  # Crockford base32, 26 chars


def test_new_ulids_are_unique():
    assert len({new_ulid() for _ in range(1000)}) == 1000


def test_new_ulids_are_lexicographically_time_ordered():
    # ULIDs minted in sequence sort in mint order (time-prefixed).
    ulids = [new_ulid() for _ in range(50)]
    assert ulids == sorted(ulids)


def test_utc_now_iso_default_is_z_suffixed_seconds():
    stamp = utc_now_iso()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp)


def test_utc_now_iso_rulebook_flavour_has_offset_no_z():
    stamp = utc_now_iso(timespec="auto", z=False)
    assert stamp.endswith("+00:00")
    assert "Z" not in stamp


def test_utc_now_iso_milliseconds():
    stamp = utc_now_iso(timespec="milliseconds")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", stamp)
