# supervisor_tools.py
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional

# 與 supervisor_prompts 的 args 對齊
class DelegateMEArgs(BaseModel):
    question: str = Field(..., description="Question for ME (about docs/definitions/physical meaning).")
    pdf_dir: str = Field("./docs", description="Directory of domain PDFs to use.")
    success_criteria: Optional[str] = Field(None, description="What a correct, complete answer looks like. ME will use this to self-check before returning.")

class DelegateDEArgs(BaseModel):
    task: str = Field(..., description="Task for DE that requires data retrieval / SQL-like queries.")
    success_criteria: Optional[str] = Field(None, description="What a correct, complete result looks like. DE will use this to self-check before returning.")

class DelegateDSArgs(BaseModel):
    task: str = Field(..., description="Task for DS that requires EDA/modeling/plots in Python.")
    success_criteria: Optional[str] = Field(None, description="What a correct, complete result looks like. DS will use this to self-check before returning.")

class FinalAnswerArgs(BaseModel):
    answer: str = Field(..., description="Synthesis to the user; cite or summarize the evidence referenced by experts.")

@tool("delegate_to_me", args_schema=DelegateMEArgs)
def delegate_to_me_tool(question: str, pdf_dir: str, success_criteria: Optional[str] = None):
    """Supervisor -> ask ME to consult domain documents and return page-cited evidence."""
    return {"ok": True, "to": "ME", "question": question, "pdf_dir": pdf_dir,
            "success_criteria": success_criteria}

@tool("delegate_to_de", args_schema=DelegateDEArgs)
def delegate_to_de_tool(task: str, success_criteria: Optional[str] = None):
    """Supervisor -> ask DE to retrieve or aggregate data using SQL-like tools."""
    return {"ok": True, "to": "DE", "task": task, "success_criteria": success_criteria}

@tool("delegate_to_ds", args_schema=DelegateDSArgs)
def delegate_to_ds_tool(task: str, success_criteria: Optional[str] = None):
    """Supervisor -> ask DS to analyze data using Python (EDA/stats/model/plots)."""
    return {"ok": True, "to": "DS", "task": task, "success_criteria": success_criteria}

@tool("final_answer", args_schema=FinalAnswerArgs)
def final_answer_tool(answer: str):
    """Supervisor -> provide the final synthesis to the user (only with evidence)."""
    return {"ok": True, "final": True}

def get_supervisor_tools():
    return [delegate_to_me_tool, delegate_to_de_tool, delegate_to_ds_tool, final_answer_tool]

