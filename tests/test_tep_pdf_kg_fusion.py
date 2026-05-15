from __future__ import annotations

import json
from pathlib import Path

from tep_pdf_kg.markdown_fusion import fuse_markdown_outputs, preclean_markdown
from tep_pdf_kg.gemini_repair import _user_prompt_from_payload, build_gemini_repair_extractor, run_fusion_repair


def test_preclean_markdown_removes_images_page_headers_and_promotes_real_headings():
    source = """![image 1](<foo.png>)
Page 1
246 J. J. DOWNS and E. F. VOGEL
INTRODUCTION
This is line one
line two
"""
    cleaned = preclean_markdown(source, "opendataloader-pdf")

    assert "![image" not in cleaned
    assert "Page 1" not in cleaned
    assert "246 J. J. DOWNS" not in cleaned
    assert "## Introduction" in cleaned
    assert "This is line one\nline two" in cleaned


def test_fuse_markdown_outputs_defers_noisy_tables_and_writes_review_candidates(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        """INTRODUCTION

The process has 12 valves available for manipulation.

Table 1. Heat and material balance data
1 2 3 4 5
0.123 0.456 0.789
""",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        """## Introduction

The process has 12 valves available for manipulation and 41 measurements available for monitoring.
""",
        encoding="utf-8",
    )

    report = fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)

    fusion_dir = out_dir / "fusion"
    canonical = (fusion_dir / "canonical.cleaned.md").read_text(encoding="utf-8")
    alignment = [json.loads(line) for line in (fusion_dir / "alignment.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    review_candidates = [
        json.loads(line) for line in (fusion_dir / "review_candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert report["doc_id"] == "DOWNS.pdf"
    assert "41 measurements available for monitoring" in canonical
    assert "Table 1. Heat and material balance data" not in canonical
    assert any(row["decision_type"] == "defer_table_review" for row in alignment)
    assert any(row["repair_candidate"] for row in review_candidates)
    assert report["deferred_table_count"] >= 1
    assert (fusion_dir / "review_candidates.jsonl").exists()


def test_fuse_markdown_outputs_keeps_docling_only_cleaner_prose(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        """PROCESS DESCRIPTION

The process has five major unit operations.
""",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        """## Process Description

The process has five major unit operations.

Products G and H exit the stripper base and are separated in a downstream refining section.
""",
        encoding="utf-8",
    )

    report = fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)
    fusion_dir = out_dir / "fusion"
    canonical = (fusion_dir / "canonical.cleaned.md").read_text(encoding="utf-8")
    alignment = [json.loads(line) for line in (fusion_dir / "alignment.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    assert "Products G and H exit the stripper base" in canonical
    assert any(row["decision_type"] == "keep_docling_prose" for row in alignment)
    assert report["prose_blocks_from_docling"] >= 1


def test_fusion_repair_writes_checkpoint_artifacts_and_rebuilds_markdown(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        """INTRODUCTION

The process has 12 valves available for manipulation.

Table 1. Heat and material balance data
1 2 3 4 5
0.123 0.456 0.789
""",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        """## Introduction

The process has 12 valves available for manipulation and 41 measurements available for monitoring.
""",
        encoding="utf-8",
    )

    fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)

    def fake_repair(payload: dict) -> dict:
        candidate = payload["candidate"]
        if candidate["decision_type"] == "defer_table_review":
            return {
                "candidate_id": candidate["candidate_id"],
                "action": "keep_deferred",
                "repaired_text": "",
                "content_type": "table_summary",
                "confidence": 0.21,
                "notes": "Table meaning not recoverable.",
            }
        return {
            "candidate_id": candidate["candidate_id"],
            "action": "replace",
            "repaired_text": candidate["docling_text"] or candidate["chosen_text"],
            "content_type": "prose",
            "confidence": 0.93,
            "notes": "Use cleaner Docling prose.",
        }

    report = run_fusion_repair(
        doc_id="DOWNS.pdf",
        output_dir=out_dir,
        extractor=fake_repair,
        max_workers=2,
    )

    repaired_md = (out_dir / "fusion" / "canonical.repaired.md").read_text(encoding="utf-8")
    repaired_report = json.loads((out_dir / "fusion" / "canonical.repaired.report.json").read_text(encoding="utf-8"))
    status_rows = [
        json.loads(line)
        for line in (out_dir / "fusion_repair" / "fusion_repair_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert report["candidate_count"] >= 1
    assert repaired_report["applied_repair_count"] >= 1
    assert "41 measurements available for monitoring" in repaired_md
    assert any(row["status"] == "succeeded" for row in status_rows)
    assert any((out_dir / "fusion_repair").glob("candidate_*.json"))


def test_fusion_repair_resume_skips_succeeded_and_retries_failed(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        """PROCESS DESCRIPTION

The process has five major unit operations.
""",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        """## Process Description

The process has five major unit operations.

Products G and H exit the stripper base and are separated in a downstream refining section.
""",
        encoding="utf-8",
    )

    fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)
    attempts: dict[str, int] = {}

    def flaky_repair(payload: dict) -> dict:
        candidate = payload["candidate"]
        candidate_id = candidate["candidate_id"]
        attempts[candidate_id] = attempts.get(candidate_id, 0) + 1
        if attempts[candidate_id] == 1:
            raise RuntimeError("repair failed once")
        return {
            "candidate_id": candidate_id,
            "action": "replace",
            "repaired_text": candidate["docling_text"],
            "content_type": "prose",
            "confidence": 0.84,
            "notes": "Recovered on retry.",
        }

    first = run_fusion_repair(doc_id="DOWNS.pdf", output_dir=out_dir, extractor=flaky_repair, max_workers=1)
    second = run_fusion_repair(doc_id="DOWNS.pdf", output_dir=out_dir, extractor=flaky_repair, resume=True, max_workers=1)

    assert first["execution_failed_this_run"] >= 1
    assert second["execution_succeeded_this_run"] >= 1
    assert second["skipped_candidate_count"] == 0
    assert sorted(attempts.values()) == [2]


def test_fusion_repair_marks_malformed_output_as_failed(tmp_path: Path):
    out_dir = tmp_path / "doc"
    odl_dir = out_dir / "opendataloader-pdf"
    docling_dir = out_dir / "docling"
    odl_dir.mkdir(parents=True)
    docling_dir.mkdir(parents=True)

    (odl_dir / "document.md").write_text(
        "INTRODUCTION\n\nThe process has 12 valves available for manipulation.\n\nTable 1. Heat and material balance data\n1 2 3\n0.4 0.5 0.6\n",
        encoding="utf-8",
    )
    (docling_dir / "document.md").write_text(
        "## Introduction\n\nThe process has 12 valves available for manipulation and 41 measurements available for monitoring.\n",
        encoding="utf-8",
    )
    fuse_markdown_outputs(doc_id="DOWNS.pdf", output_dir=out_dir)

    report = run_fusion_repair(
        doc_id="DOWNS.pdf",
        output_dir=out_dir,
        extractor=lambda payload: {"bad": "shape"},
        max_workers=1,
    )

    artifact = next((out_dir / "fusion_repair").glob("candidate_*.json"))
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert report["execution_failed_this_run"] >= 1
    assert payload["status"] == "failed"


def test_gemini_repair_extractor_uses_structured_output(monkeypatch):
    import importlib

    seen_prompt = {}

    class FakeDecision:
        def model_dump(self):
            return {
                "candidate_id": "candidate_0000",
                "action": "replace",
                "repaired_text": "Clean repaired prose.",
                "content_type": "prose",
                "confidence": 0.92,
                "notes": "Grounded in parser text.",
            }

    class FakeStructured:
        def invoke(self, prompt):
            seen_prompt["value"] = prompt
            return FakeDecision()

    class FakeLLM:
        def bind(self, **kwargs):
            return self

        def with_structured_output(self, schema):
            return FakeStructured()

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "llm", FakeLLM())
    monkeypatch.setattr(common, "invoke_with_retry", lambda fn, prompt: fn(prompt))

    extractor = build_gemini_repair_extractor()
    decision = extractor(
        {
            "candidate": {
                "candidate_id": "candidate_0000",
                "decision_type": "docling_only_prose",
                "defer_reason": "docling_only_prose",
                "heading": "Introduction",
                "section_id": "section_0001_intro",
                "block_type": "prose",
                "odl_text": "",
                "docling_text": "Clean repaired prose.",
                "chosen_text": "",
            },
            "local_context": {"previous_accepted_prose": "", "next_accepted_prose": ""},
        }
    )

    assert decision["action"] == "replace"
    assert decision["candidate_id"] == "candidate_0000"
    assert isinstance(seen_prompt["value"], list)
    assert len(seen_prompt["value"]) == 2


def test_gemini_repair_extractor_model_override_builds_new_client(monkeypatch):
    import importlib
    import langchain_google_genai

    seen = {}

    class FakeDecision:
        def model_dump(self):
            return {
                "candidate_id": "candidate_0000",
                "action": "replace",
                "repaired_text": "Clean repaired prose.",
                "content_type": "prose",
                "confidence": 0.92,
                "notes": "Grounded in parser text.",
            }

    class FakeStructured:
        def invoke(self, prompt):
            return FakeDecision()

    class FakeOverrideLLM:
        def __init__(self, **kwargs):
            seen["kwargs"] = kwargs

        def with_structured_output(self, schema):
            return FakeStructured()

        def invoke(self, prompt):
            return FakeDecision()

    class FakeBaseLLM:
        temperature = 0.25
        max_output_tokens = 8192

    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")
    common = importlib.import_module("common")
    monkeypatch.setattr(common, "llm", FakeBaseLLM())
    monkeypatch.setattr(common, "invoke_with_retry", lambda fn, prompt: fn(prompt))
    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", FakeOverrideLLM)

    extractor = build_gemini_repair_extractor(model="gemini-2.0-flash-lite")
    decision = extractor(
        {
            "candidate": {
                "candidate_id": "candidate_0000",
                "decision_type": "docling_only_prose",
                "defer_reason": "docling_only_prose",
                "heading": "Introduction",
                "section_id": "section_0001_intro",
                "block_type": "prose",
                "odl_text": "",
                "docling_text": "Clean repaired prose.",
                "chosen_text": "",
            },
            "local_context": {"previous_accepted_prose": "", "next_accepted_prose": ""},
        }
    )

    assert seen["kwargs"]["model"] == "gemini-2.0-flash-lite"
    assert decision["action"] == "replace"


def test_repair_prompt_includes_docling_only_prose_rules():
    prompt = _user_prompt_from_payload(
        {
            "candidate": {
                "candidate_id": "candidate_0001",
                "decision_type": "keep_docling_prose",
                "defer_reason": "docling_only_prose",
                "heading": "Control",
                "section_id": "section_0001_control",
                "block_type": "prose",
                "odl_text": "",
                "docling_text": "Eastman Chemical Company, Kingsport, T' N",
                "chosen_text": "Eastman Chemical Company, Kingsport, T' N",
            },
            "local_context": {"previous_accepted_prose": "", "next_accepted_prose": ""},
        }
    )

    assert "docling_only_prose" in prompt
    assert "complete, standalone sentence or paragraph" in prompt
    assert "prefer 'keep_deferred'" in prompt


def test_repair_prompt_includes_prose_conflict_rules():
    prompt = _user_prompt_from_payload(
        {
            "candidate": {
                "candidate_id": "candidate_0009",
                "decision_type": "review_required_conflict",
                "defer_reason": "prose_conflict",
                "heading": "Process Description",
                "section_id": "section_0003_process-description",
                "block_type": "prose",
                "odl_text": "The gaseous reactants are fad to the reactor where they react...",
                "docling_text": "products leave the reactor as vapors along with the unreacted feeds...",
                "chosen_text": "The gaseous reactants are fad to the reactor where they react...",
            },
            "local_context": {"previous_accepted_prose": "Prior clean paragraph.", "next_accepted_prose": "Next clean paragraph."},
        }
    )

    assert "prose_conflict" in prompt
    assert "semantically complete" in prompt
    assert "Do not splice unrelated sentence fragments together" in prompt


def test_repair_prompt_rejects_process_and_mode_hybrids():
    prompt = _user_prompt_from_payload(
        {
            "candidate": {
                "candidate_id": "candidate_0010",
                "decision_type": "review_required_conflict",
                "defer_reason": "prose_conflict",
                "heading": "Process Description",
                "section_id": "section_0003_process-description",
                "block_type": "prose",
                "odl_text": "products leave the reactor as vapors along with the Mode 1 is the base case.",
                "docling_text": "The reactor product stream passes through a cooler for condensing the products and from there to a Mode 1 is the base case.",
                "chosen_text": "The reactor product stream passes through a cooler for condensing the products and from there to a Mode 1 is the base case.",
            },
            "local_context": {
                "previous_accepted_prose": "Previous process-flow paragraph.",
                "next_accepted_prose": "Next process-flow paragraph.",
            },
        }
    )

    assert "Optimize for chunk readability over maximum information retention" in prompt
    assert "different discourse units" in prompt
    assert "from there to a" in prompt
    assert "You may keep only one coherent sub-paragraph" in prompt
