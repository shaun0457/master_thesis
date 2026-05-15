from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tep_pdf_kg import build_gemini_repair_extractor, build_pilot_manifest, run_fusion_repair


def main() -> int:
    parser = argparse.ArgumentParser(description="Run selective Gemini markdown repair for fused ODL/Docling candidates.")
    parser.add_argument("--output-root", default="artifacts/tep_pdf_kg")
    parser.add_argument("--doc", action="append", help="Optional doc_id filter. Repeatable.")
    parser.add_argument("--resume", action="store_true", help="Resume repair and skip already succeeded candidates.")
    parser.add_argument("--start-candidate", type=int, default=0, help="Start repair from this candidate index.")
    parser.add_argument("--max-candidates", type=int, default=None, help="Repair at most this many candidates.")
    parser.add_argument("--max-workers", type=int, default=1, help="Maximum parallel workers for candidate repair.")
    parser.add_argument("--gemini-model", default=None, help="Optional Gemini model override for markdown repair.")
    args = parser.parse_args()

    manifests = build_pilot_manifest(output_root=args.output_root)
    selected = set(args.doc or [])
    manifests = [manifest for manifest in manifests if not selected or manifest.doc_id in selected]
    extractor = build_gemini_repair_extractor(model=args.gemini_model)

    reports = []
    for manifest in manifests:
        reports.append(
            run_fusion_repair(
                doc_id=manifest.doc_id,
                output_dir=manifest.output_dir,
                extractor=extractor,
                start_candidate=args.start_candidate,
                max_candidates=args.max_candidates,
                resume=args.resume,
                max_workers=args.max_workers,
            )
        )

    summary_path = Path(args.output_root) / "fusion_repair_run_summary.json"
    summary_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
