"""
Pydantic schemas for all agent structured I/O.
Replaces the 4-layer fallback text parsing in delegate_tools._summarize_out.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class MEReport(BaseModel):
    """Output schema for Machine Expert (ME) after synthesize_and_cite."""
    answer: str = Field(..., min_length=5)
    citation_coverage: float = Field(0.0, ge=0.0, le=1.0)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    unresolved: List[str] = []


class DSReport(BaseModel):
    """Output schema for Data Scientist (DS) after analysis."""
    summary: str = Field(..., min_length=5)
    figures_generated: List[str] = []
    model_details: Optional[dict] = None
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class DEReport(BaseModel):
    """Output schema for Data Engineer (DE) after data delivery."""
    dataset_uri: Optional[str] = None
    row_count: Optional[int] = None
    summary: str = ""
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class JudgeScore(BaseModel):
    """Score from JudgeLLM evaluating a final_answer."""
    factual_grounding: int = Field(..., ge=0, le=3)
    completeness: int = Field(..., ge=0, le=3)
    coherence: int = Field(..., ge=0, le=3)
    critique: str


class SelfEvalResult(BaseModel):
    """Agent self-evaluation of its own last output."""
    confidence: float = Field(..., ge=0.0, le=1.0)
    completeness: float = Field(..., ge=0.0, le=1.0)
    issues: List[str] = []
