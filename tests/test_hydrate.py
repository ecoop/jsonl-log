# Copyright (c) 2026 Eric Cooper. Licensed under MIT; see LICENSE.
"""Tests for JsonlLog.hydrate() and JsonlLog.bootstrap().

Covers startup-time backend→local restore and the one-time local→backend push
for consumers adopting durability on a pre-existing log. See
docs/v0.2-plan.md §Test plan → test_hydrate.py.
"""

from __future__ import annotations

import logging

import pytest

from jsonl_log import JsonlLog

# ── hydrate() ─────────────────────────────────────────────────────────────────

def test_hydrate_no_backend_is_noop(tmp_path):
    log = JsonlLog(tmp_path / "log.jsonl")
    log.hydrate()  # must not raise
    assert not (tmp_path / "log.jsonl").exists()


def test_hydrate_populates_empty_local_from_backend(tmp_path, fake_backend):
    fake_backend.store["log.jsonl"] = '{"n": 1}\n{"n": 2}\n'

    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    log.hydrate()

    assert (tmp_path / "log.jsonl").read_text(encoding="utf-8") == '{"n": 1}\n{"n": 2}\n'
    assert [r["n"] for r in log.read_all()] == [1, 2]


def test_hydrate_overwrites_diverged_local(tmp_path, fake_backend, caplog):
    (tmp_path / "log.jsonl").write_text('{"n": 99}\n', encoding="utf-8")
    fake_backend.store["log.jsonl"] = '{"n": 1}\n'

    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    with caplog.at_level(logging.WARNING, logger="jsonl_log"):
        log.hydrate()

    assert (tmp_path / "log.jsonl").read_text(encoding="utf-8") == '{"n": 1}\n'
    assert any("differs from backend" in r.message for r in caplog.records)


def test_hydrate_empty_backend_leaves_local_alone(tmp_path, fake_backend):
    (tmp_path / "log.jsonl").write_text('{"n": 1}\n{"n": 2}\n{"n": 3}\n', encoding="utf-8")

    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    log.hydrate()

    assert [r["n"] for r in log.read_all()] == [1, 2, 3]


def test_hydrate_is_atomic_on_local_side(tmp_path, fake_backend, monkeypatch):
    # Simulate a mid-hydrate crash by making tmp.replace() blow up. The
    # existing local file must survive intact — no truncation.
    (tmp_path / "log.jsonl").write_text('{"prior": true}\n', encoding="utf-8")
    fake_backend.store["log.jsonl"] = '{"new": true}\n'

    from pathlib import Path as _Path

    real_replace = _Path.replace

    def boom(self, target):
        if str(self).endswith(".hydrate.tmp"):
            raise OSError("simulated crash mid-replace")
        return real_replace(self, target)

    monkeypatch.setattr(_Path, "replace", boom)

    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    with pytest.raises(OSError, match="simulated crash"):
        log.hydrate()

    # Local file is either the ORIGINAL content (temp-then-replace) or absent
    # (if replace failed after unlink). It must NOT be a truncated in-place
    # write. Assert the strong form: original content preserved.
    assert (tmp_path / "log.jsonl").read_text(encoding="utf-8") == '{"prior": true}\n'


def test_hydrate_after_local_appends_refuses(tmp_path, fake_backend):
    fake_backend.store["log.jsonl"] = '{"remote": true}\n'
    log = JsonlLog(tmp_path / "log.jsonl", stamp_time=False, durable_backend=fake_backend)

    log.append({"local": True})  # append THEN hydrate — a consumer bug.

    with pytest.raises(RuntimeError, match="hydrate\\(\\) called after append"):
        log.hydrate()

    # Local file untouched.
    assert (tmp_path / "log.jsonl").read_text(encoding="utf-8") == '{"local": true}\n'


def test_hydrate_after_local_appends_force_overwrites(tmp_path, fake_backend):
    # The force=True escape hatch for consumers who genuinely want to accept
    # the backend's view even after appending. Without force=True this
    # sequence raises (see previous test).
    fake_backend.store["log.jsonl"] = '{"remote": true}\n'
    log = JsonlLog(tmp_path / "log.jsonl", stamp_time=False, durable_backend=fake_backend)

    log.append({"local": True})  # also mirrored to backend by dual-write.
    log.hydrate(force=True)      # would raise without force=True.

    # After hydrate, local is byte-identical to backend — the guard was
    # bypassed and the pull happened. Backend now holds both rows because
    # the append mirrored the local row up before hydrate ran.
    assert (
        (tmp_path / "log.jsonl").read_text(encoding="utf-8")
        == fake_backend.store["log.jsonl"]
        == '{"remote": true}\n{"local": true}\n'
    )


# ── bootstrap() ───────────────────────────────────────────────────────────────

def test_bootstrap_pushes_local_when_backend_empty(tmp_path, fake_backend):
    (tmp_path / "log.jsonl").write_text('{"n": 1}\n{"n": 2}\n', encoding="utf-8")

    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    log.bootstrap()

    assert fake_backend.store["log.jsonl"] == '{"n": 1}\n{"n": 2}\n'


def test_bootstrap_noop_when_backend_has_content(tmp_path, fake_backend):
    (tmp_path / "log.jsonl").write_text('{"n": 99}\n', encoding="utf-8")
    fake_backend.store["log.jsonl"] = '{"already": "there"}\n'

    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    log.bootstrap()

    # Backend unchanged; no append calls were made.
    assert fake_backend.store["log.jsonl"] == '{"already": "there"}\n'
    assert fake_backend.append_calls == []


def test_bootstrap_no_backend_is_noop(tmp_path):
    (tmp_path / "log.jsonl").write_text('{"n": 1}\n', encoding="utf-8")
    log = JsonlLog(tmp_path / "log.jsonl")
    log.bootstrap()  # must not raise


def test_bootstrap_no_local_file_is_noop(tmp_path, fake_backend):
    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    log.bootstrap()
    assert fake_backend.store == {}
    assert fake_backend.append_calls == []


def test_hydrate_after_bootstrap_is_content_noop(tmp_path, fake_backend):
    # After bootstrap, backend == local. hydrate() then either does nothing
    # (paths agree) or overwrites with identical bytes — either way, local
    # content is unchanged and the post-append guard resets.
    (tmp_path / "log.jsonl").write_text('{"n": 1}\n{"n": 2}\n', encoding="utf-8")

    log = JsonlLog(tmp_path / "log.jsonl", durable_backend=fake_backend)
    log.bootstrap()
    log.hydrate()

    assert (tmp_path / "log.jsonl").read_text(encoding="utf-8") == '{"n": 1}\n{"n": 2}\n'
