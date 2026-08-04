# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for the read helpers: read_all, read_latest, read_latest_list."""

from __future__ import annotations

from jsonl_log import append_jsonl, read_all, read_latest, read_latest_list


def test_read_all_missing_file_is_empty(tmp_path):
    assert read_all(tmp_path / "nope.jsonl") == []


def test_read_latest_missing_file_is_empty_dict(tmp_path):
    assert read_latest(tmp_path / "nope.jsonl", "k") == {}


def test_read_all_skips_blank_lines(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"n": 1}\n\n   \n{"n": 2}\n', encoding="utf-8")
    assert [r["n"] for r in read_all(path)] == [1, 2]


def test_read_all_where_filter(tmp_path):
    path = tmp_path / "log.jsonl"
    for n in range(5):
        append_jsonl(path, {"n": n})
    evens = read_all(path, where=lambda r: r["n"] % 2 == 0)
    assert [r["n"] for r in evens] == [0, 2, 4]


def test_read_latest_last_row_wins_per_key(tmp_path):
    path = tmp_path / "feedback.jsonl"
    append_jsonl(path, {"qa_id": "a", "rating": 1})
    append_jsonl(path, {"qa_id": "b", "rating": 5})
    append_jsonl(path, {"qa_id": "a", "rating": 4})  # supersedes the first "a"
    latest = read_latest(path, "qa_id")
    assert latest["a"]["rating"] == 4
    assert latest["b"]["rating"] == 5


def test_read_latest_skips_rows_missing_the_key(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"qa_id": "a", "v": 1})
    append_jsonl(path, {"no_key": True})
    assert set(read_latest(path, "qa_id")) == {"a"}


def test_read_latest_list_sorted_newest_first(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"qa_id": "a", "timestamp": "2026-08-01T00:00:00Z"})
    append_jsonl(path, {"qa_id": "b", "timestamp": "2026-08-03T00:00:00Z"})
    append_jsonl(path, {"qa_id": "c", "timestamp": "2026-08-02T00:00:00Z"})
    rows = read_latest_list(path, "qa_id", sort_desc="timestamp")
    assert [r["qa_id"] for r in rows] == ["b", "c", "a"]


def test_read_latest_list_where_then_latest(tmp_path):
    # Emulates rulebook's read_latest_feedback: drop legacy rows, then latest.
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"qa_id": "a", "rating": "up"})   # legacy string rating
    append_jsonl(path, {"qa_id": "a", "rating": 4})
    rows = read_latest_list(path, "qa_id", where=lambda r: not isinstance(r["rating"], str))
    assert len(rows) == 1
    assert rows[0]["rating"] == 4
