#!/usr/bin/env python3
# cli/run_experiment.py
"""
CLI entrypoint for running O-MAS MAS experiments.

Supports:
- Multiple seeds (batch execution)
- All 4 protocols
- Result aggregation
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Fix Windows console encoding issue
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class Tee:
    """Simple Tee class to write to both console and file."""
    def __init__(self, console, file_path):
        self.console = console
        self.file = open(file_path, 'w', encoding='utf-8')

    def write(self, message):
        self.console.write(message)
        self.console.flush()  # ← 立即flush console
        self.file.write(message)
        self.file.flush()

    def flush(self):
        self.console.flush()
        self.file.flush()

    def close(self):
        self.file.close()


def init_run(run_id: str, protocol: str, seed: int) -> Path:
    """
    Initialize a run using init_blackboard.py.

    Returns:
        Path: Run directory path
    """
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "cli" / "init_blackboard.py"),
        "--run", run_id,
        "--protocol", protocol,
        "--prompt-version", "v2",
        "--seed", str(seed),
        "--model", os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
        "--provider", "vertex",
        "--location", os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"init_blackboard failed:\n{result.stderr}")

    return PROJECT_ROOT / "data" / "runs" / run_id


def run_single_experiment(
    query_path: Path,
    protocol: str,
    seed: int,
    max_turns: int = 20
) -> Dict[str, Any]:
    """
    Run a single experiment with one seed.

    Returns:
        dict: Run summary
    """
    # Generate run_id
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    run_id = f"{protocol}-s{seed}-{timestamp}"

    print(f"\n{'='*60}")
    print(f"Starting run: {run_id}")
    print(f"{'='*60}\n")

    try:
        # 1. Initialize run
        print(f"[1/2] Initializing blackboard...")
        run_path = init_run(run_id, protocol, seed)
        print(f"[OK] Run initialized: {run_path}")

        # 2. Execute experiment
        print(f"\n[2/2] Executing experiment...")

        # Redirect stdout to both console and stdout.txt
        stdout_file = run_path / "stdout.txt"
        original_stdout = sys.stdout
        tee = Tee(original_stdout, stdout_file)
        sys.stdout = tee

        try:
            from mas.runtime.loop import run_experiment

            model_cfg = {
                "model_name": os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
                "temperature": float(os.getenv("GEMINI_TEMP", "0.25"))
            }

            summary = run_experiment(
                protocol=protocol,
                query_path=query_path,
                run_id=run_id,
                seed=seed,
                model_cfg=model_cfg,
                max_turns=max_turns
            )

            summary["run_path"] = str(run_path)
            summary["success"] = True

            return summary

        finally:
            # Restore original stdout
            sys.stdout = original_stdout
            tee.close()

    except Exception as e:
        print(f"\n[ERROR] Run failed: {e}")
        import traceback
        traceback.print_exc()

        return {
            "run_id": run_id,
            "protocol": protocol,
            "seed": seed,
            "success": False,
            "error": str(e)
        }


def run_batch(
    query_path: Path,
    protocol: str,
    seeds: List[int],
    max_turns: int = 20
) -> List[Dict[str, Any]]:
    """
    Run experiments across multiple seeds.

    Returns:
        list: List of run summaries
    """
    results = []

    print(f"\n{'='*60}")
    print(f"BATCH EXPERIMENT")
    print(f"{'='*60}")
    print(f"Query: {query_path}")
    print(f"Protocol: {protocol}")
    print(f"Seeds: {seeds}")
    print(f"{'='*60}\n")

    for i, seed in enumerate(seeds, 1):
        print(f"\n[Run {i}/{len(seeds)}] Seed: {seed}")

        summary = run_single_experiment(
            query_path=query_path,
            protocol=protocol,
            seed=seed,
            max_turns=max_turns
        )

        results.append(summary)

        # Print summary
        if summary["success"]:
            print(f"[SUCCESS] {summary['run_id']}: {summary['turns']} turns")
        else:
            print(f"[FAILED] {summary['run_id']}: {summary.get('error', 'Unknown error')}")

    # Overall summary
    print(f"\n{'='*60}")
    print(f"BATCH SUMMARY")
    print(f"{'='*60}")
    success_count = sum(1 for r in results if r["success"])
    print(f"Total runs: {len(results)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {len(results) - success_count}")
    print(f"{'='*60}\n")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run X-MAS MAS experiments"
    )

    parser.add_argument(
        "--query",
        type=Path,
        required=True,
        help="Query/task description file (.md)"
    )

    parser.add_argument(
        "--protocol",
        choices=["neutral", "planner_to_worker", "debate", "delphi"],
        required=True,
        help="Collaboration protocol"
    )

    parser.add_argument(
        "--seeds",
        type=int,
        nargs='+',
        default=[42],
        help="Random seeds (space-separated)"
    )

    parser.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="Maximum turns per run"
    )

    args = parser.parse_args()

    # Validate query file
    if not args.query.exists():
        print(f"Error: Query file not found: {args.query}")
        return 1

    # Run batch
    results = run_batch(
        query_path=args.query,
        protocol=args.protocol,
        seeds=args.seeds,
        max_turns=args.max_turns
    )

    # Exit code: 0 if all succeeded, 1 if any failed
    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
