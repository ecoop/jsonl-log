# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for the raw `append_jsonl` write path."""

from __future__ import annotations

import json

from jsonl_log import append_jsonl


def test_append_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "log.jsonl"
    append_jsonl(path, {"a": 1})
    assert path.exists()


def test_append_writes_one_json_line_per_call(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"n": 1})
    append_jsonl(path, {"n": 2})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["n"] for line in lines] == [1, 2]


def test_append_each_line_is_newline_terminated(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"n": 1})
    append_jsonl(path, {"n": 2})
    assert path.read_text(encoding="utf-8").endswith("}\n")
    # No blank/partial lines between records.
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_append_preserves_unicode_by_default(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"name": "café ☕ persönlich"})
    raw = path.read_text(encoding="utf-8")
    assert "café ☕ persönlich" in raw
    assert "\\u" not in raw


def test_append_can_escape_non_ascii_when_requested(tmp_path):
    path = tmp_path / "log.jsonl"
    append_jsonl(path, {"name": "café"}, ensure_ascii=True)
    assert "\\u00e9" in path.read_text(encoding="utf-8")
