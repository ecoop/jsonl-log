# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for JsonlLog dual-write behavior with a durable backend.

Uses the FakeDurableBackend fixture from conftest.py. No google-cloud-storage
dependency. See docs/v0.2-plan.md §Test plan → test_dual_write.py.
"""

from __future__ import annotations

import json
import logging

import pytest

from jsonl_log import DurableBackendError, JsonlLog


def test_no_backend_is_unchanged(tmp_path):
    # Smoke: without a backend, JsonlLog behaves byte-for-byte like v0.1.
    log = JsonlLog(tmp_path / "log.jsonl", stamp_id=True)
    row_id = log.append({"note": "hi"})
    (row,) = log.read_all()
    assert row["id"] == row_id
    assert row["note"] == "hi"


def test_append_writes_local_and_backend(tmp_path, fake_backend):
    log = JsonlLog(
        tmp_path / "feedback.jsonl",
        stamp_time=False,  # deterministic row for byte-comparison
        durable_backend=fake_backend,
    )
    log.append({"qa_id": "q1", "rating": 5})

    (local_row,) = log.read_all()
    assert local_row == {"qa_id": "q1", "rating": 5}
    assert len(fake_backend.append_calls) == 1
    name, line = fake_backend.append_calls[0]
    assert name == "feedback.jsonl"
    # Backend saw the exact same serialized line — same JSON, same trailing "\n".
    assert line.endswith("\n")
    assert json.loads(line) == local_row
    # Local file and backend store agree byte-for-byte.
    assert (tmp_path / "feedback.jsonl").read_text(encoding="utf-8") == fake_backend.store[name]


def test_default_durable_name_is_path_basename(tmp_path, fake_backend):
    log = JsonlLog(
        tmp_path / "nested" / "dir" / "feedback.jsonl",
        stamp_time=False,
        durable_backend=fake_backend,
    )
    log.append({"n": 1})
    assert fake_backend.append_calls[0][0] == "feedback.jsonl"


def test_explicit_durable_name_overrides_default(tmp_path, fake_backend):
    log = JsonlLog(
        tmp_path / "feedback.jsonl",
        stamp_time=False,
        durable_backend=fake_backend,
        durable_name="logs/rulebook/feedback.jsonl",
    )
    log.append({"n": 1})
    assert fake_backend.append_calls[0][0] == "logs/rulebook/feedback.jsonl"


def test_backend_failure_soft_by_default(tmp_path, fake_backend, caplog):
    log = JsonlLog(
        tmp_path / "log.jsonl",
        stamp_time=False,
        durable_backend=fake_backend,
    )
    fake_backend.fail_next = True

    with caplog.at_level(logging.WARNING, logger="jsonl_log"):
        # Must NOT raise — soft failure is the default.
        log.append({"n": 1})

    # Row IS on local disk despite backend failure.
    (row,) = log.read_all()
    assert row == {"n": 1}

    # Warning was logged with the object name so operators can grep for it.
    assert any(
        "durable backend append failed" in r.message and "log.jsonl" in r.message
        for r in caplog.records
    )

    # Backend store did NOT receive the row (fail_next rejected it).
    assert fake_backend.store.get("log.jsonl") in (None, "")


def test_backend_failure_strict_raises(tmp_path, fake_backend):
    log = JsonlLog(
        tmp_path / "log.jsonl",
        stamp_time=False,
        durable_backend=fake_backend,
        strict=True,
    )
    fake_backend.fail_next = True

    with pytest.raises(DurableBackendError) as excinfo:
        log.append({"n": 1})

    # Error chains the underlying RuntimeError for provenance.
    assert isinstance(excinfo.value.__cause__, RuntimeError)

    # Documented behavior: local write already committed; no rollback.
    (row,) = log.read_all()
    assert row == {"n": 1}


def test_read_helpers_are_local_only(tmp_path, fake_backend):
    # Prime backend store as if a previous instance had written there.
    fake_backend.store["log.jsonl"] = '{"qa_id": "seed", "rating": 5}\n'

    log = JsonlLog(
        tmp_path / "log.jsonl",
        stamp_time=False,
        durable_backend=fake_backend,
    )
    # Local file is empty; read helpers must NOT reach the backend.
    assert log.read_all() == []
    assert log.read_latest("qa_id") == {}
    assert log.read_latest_list("qa_id") == []
    # No append calls happened.
    assert fake_backend.append_calls == []


def test_one_backend_serves_multiple_logs(tmp_path, fake_backend):
    feedback = JsonlLog(
        tmp_path / "feedback.jsonl",
        stamp_time=False,
        durable_backend=fake_backend,
    )
    curation = JsonlLog(
        tmp_path / "curation.jsonl",
        stamp_time=False,
        durable_backend=fake_backend,
    )
    feedback.append({"qa_id": "a", "rating": 5})
    curation.append({"qa_id": "a", "included": True})

    assert set(fake_backend.store) == {"feedback.jsonl", "curation.jsonl"}
    assert "rating" in fake_backend.store["feedback.jsonl"]
    assert "included" in fake_backend.store["curation.jsonl"]
