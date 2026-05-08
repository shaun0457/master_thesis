"""
TDD tests for structured_outputs.py — written BEFORE implementation.
"""
import pytest
from pydantic import ValidationError


def test_me_report_accepts_valid_coverage():
    from structured_outputs import MEReport
    r = MEReport(answer="The reactor temperature rises.", citation_coverage=0.8, confidence=0.9)
    assert r.citation_coverage == 0.8
    assert r.confidence == 0.9


def test_me_report_rejects_coverage_above_one():
    from structured_outputs import MEReport
    with pytest.raises(ValidationError):
        MEReport(answer="test answer here", citation_coverage=1.5)


def test_me_report_rejects_coverage_below_zero():
    from structured_outputs import MEReport
    with pytest.raises(ValidationError):
        MEReport(answer="test answer here", citation_coverage=-0.1)


def test_me_report_rejects_short_answer():
    from structured_outputs import MEReport
    with pytest.raises(ValidationError):
        MEReport(answer="no", citation_coverage=0.5)


def test_me_report_defaults():
    from structured_outputs import MEReport
    r = MEReport(answer="A valid answer here.")
    assert r.citation_coverage == 0.0
    assert r.confidence == 0.5
    assert r.unresolved == []


def test_ds_report_accepts_valid():
    from structured_outputs import DSReport
    r = DSReport(summary="Analysis complete.", figures_generated=["fig1.png"])
    assert r.summary == "Analysis complete."
    assert r.figures_generated == ["fig1.png"]


def test_ds_report_rejects_short_summary():
    from structured_outputs import DSReport
    with pytest.raises(ValidationError):
        DSReport(summary="no")


def test_de_report_optional_fields():
    from structured_outputs import DEReport
    r = DEReport()
    assert r.dataset_uri is None
    assert r.row_count is None
    assert r.confidence == 0.5


def test_judge_score_accepts_valid():
    from structured_outputs import JudgeScore
    s = JudgeScore(factual_grounding=2, completeness=3, coherence=1, critique="Needs more citations.")
    assert s.factual_grounding == 2


def test_judge_score_rejects_above_three():
    from structured_outputs import JudgeScore
    with pytest.raises(ValidationError):
        JudgeScore(factual_grounding=4, completeness=2, coherence=1, critique="ok")


def test_judge_score_rejects_below_zero():
    from structured_outputs import JudgeScore
    with pytest.raises(ValidationError):
        JudgeScore(factual_grounding=-1, completeness=2, coherence=1, critique="ok")


def test_self_eval_parse_from_json():
    from structured_outputs import SelfEvalResult
    raw = '{"confidence": 0.8, "completeness": 0.9, "issues": []}'
    r = SelfEvalResult.model_validate_json(raw)
    assert r.confidence == 0.8
    assert r.completeness == 0.9
    assert r.issues == []


def test_self_eval_with_issues():
    from structured_outputs import SelfEvalResult
    raw = '{"confidence": 0.4, "completeness": 0.6, "issues": ["missing citation", "ambiguous claim"]}'
    r = SelfEvalResult.model_validate_json(raw)
    assert len(r.issues) == 2


def test_self_eval_rejects_invalid_confidence():
    from structured_outputs import SelfEvalResult
    with pytest.raises(ValidationError):
        SelfEvalResult(confidence=1.5, completeness=0.5)
