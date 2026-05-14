"""File-drop watcher — POST any new parquet/CSV in inbox/ to /diagnose.

Simulates SCADA/historian batch integration: drop a file in the watched folder
and the MAS auto-diagnoses it.

Usage:
    python file_watcher.py --inbox inbox --url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx


SUPPORTED_SUFFIXES = {".parquet", ".csv"}


def _scan(inbox: Path) -> set[str]:
    if not inbox.exists():
        return set()
    return {p.name for p in inbox.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES}


def _diagnose_file(client: httpx.Client, url: str, path: Path) -> dict:
    r = client.post(
        f"{url.rstrip('/')}/diagnose",
        json={"observation_path": str(path.resolve())},
        timeout=180.0,
    )
    return {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text}


def watch(inbox: Path, url: str, poll_interval: float = 2.0) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    seen = _scan(inbox)
    print(f"[watch] inbox={inbox} url={url} ({len(seen)} existing files ignored)")
    with httpx.Client() as client:
        try:
            while True:
                current = _scan(inbox)
                new = sorted(current - seen)
                for name in new:
                    path = inbox / name
                    print(f"[new] {path}")
                    result = _diagnose_file(client, url, path)
                    print(f"  → {json.dumps(result.get('body'), ensure_ascii=False)[:300]}")
                seen = current
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\n[stop] watcher exiting")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--inbox", default="inbox", help="Folder to watch")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--poll", type=float, default=2.0, help="Poll interval seconds")
    args = p.parse_args()
    watch(Path(args.inbox), args.url, args.poll)


if __name__ == "__main__":
    main()
