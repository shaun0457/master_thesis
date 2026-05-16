"""Tests for the stateful stream simulator (Phase TS).

Covers: pattern parsing, cursor walk advancement, run roll-over, phase
transitions reset cursor, payload shape includes sample_idx + simulationrun.
"""
from __future__ import annotations

import os
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")

import sqlite3
from pathlib import Path

import pytest


def test_parse_pattern_supports_normal_and_fault():
    from simulation.stream_simulator import parse_pattern

    phases = parse_pattern("normal:60,fault4:30,fault8:15")
    assert len(phases) == 3
    assert phases[0].fault == 0
    assert phases[0].duration_s == 60.0
    assert phases[1].fault == 4
    assert phases[2].fault == 8
    assert phases[2].duration_s == 15.0


def test_parse_pattern_rejects_bad_spec():
    from simulation.stream_simulator import parse_pattern
    with pytest.raises(ValueError):
        parse_pattern("garbage:10")


def _make_mini_db(tmp_path: Path) -> str:
    """Synthetic DB with 2 runs per fault (4 and 0), 10 samples each."""
    db = tmp_path / "mini.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("""
            CREATE TABLE process_data (
                faultnumber REAL, simulationrun INTEGER, sample INTEGER,
                xmeas_1 REAL, xmeas_9 REAL, xmv_6 REAL
            )
        """)
        for fault in (0, 4):
            for run in (1, 2):
                for s in range(1, 11):
                    conn.execute(
                        "INSERT INTO process_data VALUES (?, ?, ?, ?, ?, ?)",
                        (float(fault), run, s, 0.1, 100.0 + s, 42.0),
                    )
        conn.commit()
    finally:
        conn.close()
    return str(db)


def test_build_cursor_picks_a_run():
    from simulation.stream_simulator import _build_cursor
    import tempfile
    import pathlib

    tmp_dir = pathlib.Path(tempfile.mkdtemp())
    db = _make_mini_db(tmp_dir)
    conn = sqlite3.connect(db)
    try:
        cursor = _build_cursor(conn, fault=4, seed=0, run_idx=1, start_sample=3)
    finally:
        conn.close()
    assert cursor is not None
    assert cursor.fault == 4
    assert cursor.run_idx == 1
    assert cursor.next_sample == 3
    assert cursor.available_runs == [1, 2]


def test_build_cursor_returns_none_for_unknown_fault(tmp_path):
    from simulation.stream_simulator import _build_cursor
    db = _make_mini_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        cursor = _build_cursor(conn, fault=99, seed=0)
    finally:
        conn.close()
    assert cursor is None


def test_walk_one_tick_advances_sample_idx_linearly(tmp_path):
    from simulation.stream_simulator import _build_cursor, _walk_one_tick
    db = _make_mini_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        cursor = _build_cursor(conn, fault=4, seed=0, run_idx=1, start_sample=1)
        first = _walk_one_tick(conn, cursor, 3)
        second = _walk_one_tick(conn, cursor, 3)
    finally:
        conn.close()
    assert [r["sample_idx"] for r in first] == [1, 2, 3]
    assert [r["sample_idx"] for r in second] == [4, 5, 6]
    # payload strips label columns
    for r in first:
        assert "faultnumber" not in r["payload"]
        assert "simulationrun" not in r["payload"]
        assert r["simulationrun"] == 1


def test_walk_one_tick_rolls_over_to_next_run(tmp_path):
    from simulation.stream_simulator import _build_cursor, _walk_one_tick

    db = _make_mini_db(tmp_path)
    conn = sqlite3.connect(db)
    try:
        # Start near end of run 1 (which has only 10 samples)
        cursor = _build_cursor(conn, fault=4, seed=0, run_idx=1, start_sample=9)
        batch = _walk_one_tick(conn, cursor, 4)
    finally:
        conn.close()
    runs_seen = {r["simulationrun"] for r in batch}
    # Should span both run 1 (samples 9, 10) and run 2 (samples 1, 2)
    assert runs_seen == {1, 2}
    assert [r["sample_idx"] for r in batch] == [9, 10, 1, 2]


def test_post_observations_includes_sample_axis_arrays():
    from simulation.stream_simulator import _post_observations

    captured = {}

    class FakeResp:
        status_code = 200
        text = "ok"

    class FakeClient:
        def post(self, url, json=None, timeout=None):
            captured["json"] = json
            return FakeResp()

    batch = [
        {"payload": {"xmeas_9": 105.0}, "sample_idx": 1, "simulationrun": 1},
        {"payload": {"xmeas_9": 106.0}, "sample_idx": 2, "simulationrun": 1},
    ]
    ok = _post_observations(FakeClient(), "http://x", batch, 4, "simulator")
    assert ok is True
    payload = captured["json"]
    assert payload["sample_indices"] == [1, 2]
    assert payload["simulationruns"] == [1, 1]
    assert payload["true_fault_hidden"] == 4
    assert payload["rows"] == [{"xmeas_9": 105.0}, {"xmeas_9": 106.0}]


def test_post_observations_handles_non_200():
    from simulation.stream_simulator import _post_observations

    class FakeResp:
        status_code = 500
        text = "internal"

    class FakeClient:
        def post(self, *a, **kw):
            return FakeResp()

    assert _post_observations(FakeClient(), "http://x", [], 0, "sim") is False


def test_run_once_full_flow(tmp_path, monkeypatch):
    from simulation.stream_simulator import run_once

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
    code = run_once("http://x", db, fault=4, rows=5, seed=0,
                    run_idx=1, start_sample=1)
    assert code == 0
    payload = posted["json"]
    assert len(payload["rows"]) == 5
    assert payload["sample_indices"] == [1, 2, 3, 4, 5]
    assert payload["true_fault_hidden"] == 4
