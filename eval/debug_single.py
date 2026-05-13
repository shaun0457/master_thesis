"""Debug script: run a single ME question and dump messages trace."""
import os, sys
from pathlib import Path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from common import AgentState
from supervisor_workflow import build_team_graph
from langchain_core.messages import HumanMessage, AIMessage

graph = build_team_graph()
Q = "How many distinct fault types are there in the TEP benchmark dataset?"
init_state = {
    "messages": [HumanMessage(content=Q)],
    "metrics": {},
    "blackboard": {},
}

try:
    final_state = graph.invoke(init_state)
    print("=== MESSAGES ===")
    for i, msg in enumerate(final_state.get("messages", [])):
        mtype = type(msg).__name__
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            tc_names = [tc.get("name") for tc in msg.tool_calls]
            print(f"  [{i}] {mtype}: tool_calls={tc_names}")
        if hasattr(msg, "content"):
            content = msg.content
            if isinstance(content, str):
                print(f"  [{i}] {mtype}: content={repr(content[:200])}")
            elif isinstance(content, list):
                txt = " ".join(c.get("text","") for c in content if isinstance(c,dict))
                print(f"  [{i}] {mtype}: content(list blocks)={repr(txt[:200])}")
        print()
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback; traceback.print_exc()
