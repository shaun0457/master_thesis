# supervisor_tools.py
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# 與 supervisor_prompts 的 args 對齊
class DelegateMEArgs(BaseModel):
    question: str = Field(..., description="Question for ME (about docs/definitions/physical meaning).")
    pdf_dir: str = Field("./docs", description="Directory of domain PDFs to use.")

class DelegateDEArgs(BaseModel):
    task: str = Field(..., description="Task for DE that requires data retrieval / SQL-like queries.")

class DelegateDSArgs(BaseModel):
    task: str = Field(..., description="Task for DS that requires EDA/modeling/plots in Python.")

class FinalAnswerArgs(BaseModel):
    answer: str = Field(..., description="Synthesis to the user; cite or summarize the evidence referenced by experts.")

@tool("delegate_to_me", args_schema=DelegateMEArgs)
def delegate_to_me_tool(question: str, pdf_dir: str):
    """Supervisor -> ask ME to consult domain documents and return page-cited evidence."""
    # 真正執行在 router；這裡只回顯，便於 llm 做工具呼叫
    return {"ok": True, "to": "ME", "question": question, "pdf_dir": pdf_dir}

@tool("delegate_to_de", args_schema=DelegateDEArgs)
def delegate_to_de_tool(task: str):
    """Supervisor -> ask DE to retrieve or aggregate data using SQL-like tools."""
    return {"ok": True, "to": "DE", "task": task}

@tool("delegate_to_ds", args_schema=DelegateDSArgs)
def delegate_to_ds_tool(task: str):
    """Supervisor -> ask DS to analyze data using Python (EDA/stats/model/plots)."""
    return {"ok": True, "to": "DS", "task": task}

@tool("final_answer", args_schema=FinalAnswerArgs)
def final_answer_tool(answer: str):
    """Supervisor -> provide the final synthesis to the user (only with evidence)."""
    return {"ok": True, "final": True}

def get_supervisor_tools():
    return [delegate_to_me_tool, delegate_to_de_tool, delegate_to_ds_tool, final_answer_tool]

