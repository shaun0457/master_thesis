"""Tests for stream_simulator pattern parsing + row fetching + posting."""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_parse_pattern_supports_normal_and_fault():
    from stream_simulator import parse_pattern

    phases = parse_pattern("normal:60,fault4:30,fault8:15")
    assert len(phases) == 3
    assert phases[0].fault == 0
    assert phases[0].duration_s == 60.0
    assert phases[1].fault == 4
    assert phases[2].fault == 8
    assert phases[2].duration_s == 15.0


def test_parse_pattern_rejects_bad_spec():
    from stream_simulator import parse_pattern
    with pytest.raises(ValueError):
        parse_pattern("garbage:10")


def _make_mini_db(tmp_path: Path) -> str:
    db = tmp_path / "mini.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("""
            CREATE TABLE process_data (
                faultnumber REAL, simulationrun INTEGER, sample INTEGER,
                xmeas_1 REAL, xmeas_9 REAL, xmv_6 REAL
            )
        """)
        # Two runs of fault=4
        for run in (1, 2):
            for s in range(1, 6):
                conn.execute(
                    "INSERT INTO process_data VALUES (?, ?, ?, ?, ?, ?)",
                    (4.0, run, s, 0.1, 120.0 + s, 42.0),
                )
        conn.commit()
    finally:
        conn.close()
    return str(db)


def test_fetch_rows_strips_label_columns(tmp_path):
    from stream_simulator import _fetch_rows

    db = _make_mini_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        rows = _fetch_rows(conn, fault=4, n=3, seed=0)
    finally:
        conn.close()

    assert len(rows) == 3
    for row in rows:
        assert "faultnumber" not in row
        assert "simulationrun" not in row
        assert "xmeas_9" in row


def test_post_observations_sends_payload(monkeypatch):
    from stream_simulator import _post_observations

    captured = {}

    class FakeResp:
        status_code = 200
        text = "ok"

    class FakeClient:
        def post(self, url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResp()

    ok = _post_observations(FakeClient(), "http://x", [{"xmeas_9": 120.0}], 4, "simulator")
    assert ok is True
    assert captured["url"].endswith("/observations")
    assert captured["json"]["true_fault_hidden"] == 4
    assert captured["json"]["source"] == "simulator"
    assert captured["json"]["rows"] == [{"xmeas_9": 120.0}]


def test_post_observations_handles_non_200():
    from stream_simulator import _post_observations

    class FakeResp:
        status_code = 500
        text = "internal"

    class FakeClient:
        def post(self, *a, **kw):
            return FakeResp()

    assert _post_observations(FakeClient(), "http://x", [{}], 0, "simulator") is False


def test_run_once_full_flow(tmp_path, monkeypatch):
    from stream_simulator import run_once

    db = _make_mini_db(tmp_path)

    posted = {}

    class FakeResp:
        status_code = 200
        text = "ok"

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, timeout=None):
            posted["json"] = json
            return FakeResp()

    monkeypatch.setattr("stream_simulator.httpx.Client", lambda: FakeClient())
    code = run_once("http://x", db, fault=4, rows=4, seed=0)
    assert code == 0
    assert len(posted["json"]["rows"]) == 4
    assert posted["json"]["true_fault_hidden"] == 4
