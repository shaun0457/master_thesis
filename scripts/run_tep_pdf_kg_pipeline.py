from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from tep_pdf_kg import build_gemini_extractor, build_pilot_manifest, run_document_pipeline


def _get_driver():
    uri = os.environ.get("NEO4J_URI", "").strip()
    if not uri:
        return None
    from neo4j import GraphDatabase

    user = os.environ.get("NEO4J_USER", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    return GraphDatabase.driver(uri, auth=(user, password))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Neo4j-first TEP PDF KG v1 pipeline.")
    parser.add_argument("--output-root", default="artifacts/tep_pdf_kg")
    parser.add_argument("--doc", action="append", help="Optional doc_id filter. Repeatable.")
    parser.add_argument("--import-neo4j", action="store_true", help="Import validated claims into Neo4j.")
    parser.add_argument("--extractor", choices=["heuristic", "gemini"], default="heuristic")
    parser.add_argument("--gemini-model", default=None, help="Optional Gemini model override for claim extraction.")
    args = parser.parse_args()

    manifests = build_pilot_manifest(output_root=args.output_root)
    selected = set(args.doc or [])
    manifests = [manifest for manifest in manifests if not selected or manifest.doc_id in selected]

    extractor = None
    if args.extractor == "gemini":
        extractor = build_gemini_extractor(model=args.gemini_model)

    driver = _get_driver() if args.import_neo4j else None
    try:
        summaries = [run_document_pipeline(manifest, extractor=extractor, neo4j_driver=driver) for manifest in manifests]
    finally:
        if driver is not None:
            driver.close()

    Path(args.output_root).mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.output_root) / "pilot_run_summary.json"
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
