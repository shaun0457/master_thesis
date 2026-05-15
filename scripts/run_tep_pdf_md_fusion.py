from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tep_pdf_kg import build_pilot_manifest, fuse_markdown_outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Fuse ODL and Docling markdown into a chunk-ready canonical markdown.")
    parser.add_argument("--output-root", default="artifacts/tep_pdf_kg")
    parser.add_argument("--doc", action="append", help="Optional doc_id filter. Repeatable.")
    parser.add_argument("--base-parser", default="opendataloader-pdf")
    parser.add_argument("--secondary-parser", default="docling")
    args = parser.parse_args()

    manifests = build_pilot_manifest(output_root=args.output_root)
    selected = set(args.doc or [])
    manifests = [manifest for manifest in manifests if not selected or manifest.doc_id in selected]

    reports = []
    for manifest in manifests:
        reports.append(
            fuse_markdown_outputs(
                doc_id=manifest.doc_id,
                output_dir=manifest.output_dir,
                base_parser=args.base_parser,
                secondary_parser=args.secondary_parser,
            )
        )

    summary_path = Path(args.output_root) / "fusion_run_summary.json"
    summary_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
