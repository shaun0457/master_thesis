from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _seed_env() -> None:
    os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-local-check")


def _build_client(tmp_dir: Path):
    from fastapi.testclient import TestClient
    import api_server

    api_server.BUFFER_DB = str(tmp_dir / "buf.db")
    return TestClient(api_server.app)


def _seed_observations(client, *, source: str = "manual", n: int = 8, true_fault: int = 4) -> None:
    rows = [{"xmeas_9": 100.0 + i, "xmeas_7": 50.0, "xmv_6": 25.0} for i in range(n)]
    resp = client.post(
        "/observations",
        json={
            "source": source,
            "true_fault_hidden": true_fault,
            "rows": rows,
            "sample_indices": list(range(1, n + 1)),
            "simulationruns": [1] * n,
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"failed to seed observations: {resp.status_code} {resp.text}")


def smoke_inline_mock() -> int:
    _print_header("API Inline Smoke")
    _seed_env()
    from simulation.diagnose_flow import DiagnosisResult

    with tempfile.TemporaryDirectory() as tmp:
        client = _build_client(Path(tmp))
        fake_result = DiagnosisResult(
            run_id="diag_inline_mock",
            ts=1.0,
            observation_path="inline",
            predicted_fault=4,
            fault_name="IDV_4",
            confidence=0.91,
            evidence_sensors=["xmeas_9", "xmeas_7"],
            top_candidates=[{"fault_id": 4, "score": 0.91, "matched": ["xmeas_9", "xmeas_7"]}],
            summary="Mock inline diagnosis succeeded.",
            true_fault=4,
            tool_events_count=3,
        )
        with patch("diagnose_flow.diagnose", return_value=fake_result):
            resp = client.post(
                "/diagnose",
                json={
                    "rows": [{"xmeas_9": 120.0, "xmeas_7": 50.0, "xmv_6": 25.0}],
                    "true_fault": 4,
                },
            )
        print(resp.json())
        return 0 if resp.status_code == 200 else 1


def smoke_window_mock() -> int:
    _print_header("API Window Smoke")
    _seed_env()
    from simulation.diagnose_flow import DiagnosisResult

    with tempfile.TemporaryDirectory() as tmp:
        client = _build_client(Path(tmp))
        _seed_observations(client, n=10, true_fault=4)

        def fake_diagnose(observation_path, true_fault, buffer_db, recursion_limit, obs_ids):
            return DiagnosisResult(
                run_id="diag_window_mock",
                ts=1.0,
                observation_path=observation_path,
                predicted_fault=4,
                fault_name="IDV_4",
                confidence=0.88,
                evidence_sensors=["xmeas_9", "xmeas_7"],
                top_candidates=[{"fault_id": 4, "score": 0.88, "matched": ["xmeas_9", "xmeas_7"]}],
                summary=f"Mock window diagnosis succeeded on {len(obs_ids)} rows.",
                true_fault=true_fault,
                tool_events_count=2,
            )

        with patch("diagnose_flow.diagnose", side_effect=fake_diagnose):
            resp = client.post("/diagnose/window", json={"window_size": 5})
        print(resp.json())
        return 0 if resp.status_code == 200 else 1


def smoke_window_real() -> int:
    _print_header("API Window Real")
    _seed_env()
    with tempfile.TemporaryDirectory() as tmp:
        client = _build_client(Path(tmp))
        _seed_observations(client, n=10, true_fault=4)
        resp = client.post("/diagnose/window", json={"window_size": 5})
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0 if resp.status_code == 200 else 1


def run_pytest(expr: str | None = None) -> int:
    _print_header("Pytest Slice")
    cmd = [sys.executable, "-m", "pytest", "-q", "--basetemp", str(ROOT / "._pytest_tmp_diagnose_checks")]
    if expr:
        cmd.extend(expr.split())
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run quick diagnosis checks without manually starting the API server."
    )
    parser.add_argument(
        "--mode",
        choices=["inline-mock", "window-mock", "window-real", "pytest-api", "pytest-diagnose", "all-mock"],
        default="window-mock",
    )
    args = parser.parse_args()

    actions: dict[str, Callable[[], int]] = {
        "inline-mock": smoke_inline_mock,
        "window-mock": smoke_window_mock,
        "window-real": smoke_window_real,
        "pytest-api": lambda: run_pytest("tests/test_api_server.py tests/test_diagnose_window.py"),
        "pytest-diagnose": lambda: run_pytest(
            "tests/test_api_server.py tests/test_diagnose_window.py tests/test_diagnose_e2e.py tests/test_diagnose_flow.py"
        ),
        "all-mock": lambda: max(smoke_inline_mock(), smoke_window_mock(), run_pytest("tests/test_api_server.py tests/test_diagnose_window.py")),
    }
    return actions[args.mode]()


if __name__ == "__main__":
    raise SystemExit(main())
