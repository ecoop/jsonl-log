# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for the JsonlLog convenience class and its auto-stamping."""

from __future__ import annotations

import re

from jsonl_log import JsonlLog


def test_stamps_time_by_default(tmp_path):
    log = JsonlLog(tmp_path / "log.jsonl")
    log.append({"note": "hi"})
    (row,) = log.read_all()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", row["timestamp"])


def test_stamp_id_mints_and_returns_ulid(tmp_path):
    log = JsonlLog(tmp_path / "log.jsonl", stamp_id=True)
    row_id = log.append({"note": "hi"})
    assert isinstance(row_id, str) and len(row_id) == 26
    (row,) = log.read_all()
    assert row["id"] == row_id


def test_append_returns_none_without_stamp_id(tmp_path):
    log = JsonlLog(tmp_path / "log.jsonl")
    assert log.append({"note": "hi"}) is None


def test_stamp_id_preserves_caller_supplied_id(tmp_path):
    log = JsonlLog(tmp_path / "log.jsonl", stamp_id=True)
    row_id = log.append({"id": "CALLER123", "note": "hi"})
    assert row_id == "CALLER123"


def test_preset_timestamp_is_not_overwritten(tmp_path):
    # The pitchcraft da_notes case: a whole batch shares one timestamp.
    log = JsonlLog(tmp_path / "log.jsonl")
    shared = "2026-01-01T00:00:00Z"
    for i in range(3):
        log.append({"i": i, "timestamp": shared})
    assert {r["timestamp"] for r in log.read_all()} == {shared}


def test_schema_version_stamped_when_configured(tmp_path):
    log = JsonlLog(tmp_path / "log.jsonl", schema_version=2)
    log.append({"note": "hi"})
    (row,) = log.read_all()
    assert row["schema_version"] == 2


def test_custom_field_names_rulebook_flavour(tmp_path):
    # rulebook stamps a "v" version, no id, isoformat()-style timestamp.
    log = JsonlLog(
        tmp_path / "feedback.jsonl",
        schema_version=3,
        version_field="v",
        timespec="auto",
        z=False,
    )
    log.append({"qa_id": "a", "rating": 5})
    (row,) = log.read_all()
    assert row["v"] == 3
    assert "id" not in row
    assert row["timestamp"].endswith("+00:00")


def test_round_trip_latest_per_key(tmp_path):
    log = JsonlLog(tmp_path / "log.jsonl", schema_version=1, version_field="v")
    log.append({"qa_id": "a", "included": True})
    log.append({"qa_id": "a", "included": False})
    latest = log.read_latest("qa_id")
    assert latest["a"]["included"] is False


def test_separate_logs_do_not_share_a_lock_but_are_independent(tmp_path):
    a = JsonlLog(tmp_path / "a.jsonl", stamp_id=True)
    b = JsonlLog(tmp_path / "b.jsonl", stamp_id=True)
    a.append({"x": 1})
    b.append({"y": 2})
    assert len(a.read_all()) == 1
    assert len(b.read_all()) == 1
