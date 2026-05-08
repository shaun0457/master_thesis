# supervisor_workflow.py (附带纠错节点和智能路由的最终版)
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, ToolMessage, BaseMessage, AIMessage
from prompt_builder import get_system_prompt
from common import llm, AgentState
from supervisor_tools import get_supervisor_tools
# from supervisor_prompts import SUPERVISOR_SYSTEM_PROMPT
from router import route_and_execute
from bb_tools import get_bb_snapshot


# ----- 辅助函数 (保持不变) -----

def _summ_tool_msg(m: ToolMessage) -> str:
    import json
    txt = str(getattr(m, "content", ""))[:4000]
    try:
        d = json.loads(txt);
        r = d.get("result", d);
        parts = []
        if isinstance(r, dict):
            if "agent" in r: parts.append(f"agent={r.get('agent')}")
            if "summary" in r: parts.append(f"summary={str(r.get('summary'))[:800]}")
            if r.get("delegate_requests"): parts.append(f"delegate_requests={r['delegate_requests']}")
            if parts: return f"{m.name}: " + " | ".join(parts)
        return f"{m.name}: {txt[:800]}"
    except Exception:
        return f"{m.name}: {txt[:800]}"


def _coerce_for_gemini(msgs: List[BaseMessage]) -> List[BaseMessage]:
    if not msgs: return msgs
    last_non_tool = -1
    for i in range(len(msgs) - 1, -1, -1):
        if not isinstance(msgs[i], ToolMessage): last_non_tool = i; break
    if last_non_tool == len(msgs) - 1: return msgs
    tail_tools = msgs[last_non_tool + 1:]
    lines = [_summ_tool_msg(m) for m in tail_tools if isinstance(m, ToolMessage)]
    summary = "Tools reported:\n- " + "\n- ".join(
        lines) + "\n\nBased on the above, choose exactly ONE action (delegate_to_me/de/ds or final_answer)."
    return msgs[:last_non_tool + 1] + [HumanMessage(content=summary)]


def _ensure_init(state: Dict[str, Any]) -> Dict[str, Any]:
    state.setdefault("messages", []);
    state.setdefault("blackboard", {"facts": [], "datasets": [], "citations": [], "open_issues": []});
    state.setdefault("tool_events", []);
    state.setdefault("delegations", []);
    state.setdefault("metrics", {})
    return state


def _has_min_evidence(state: dict) -> bool:
    bb = state.get("blackboard", {}) if isinstance(state.get("blackboard"), dict) else {}
    if bb.get("facts") or bb.get("datasets"):
        return True
    try:
        snap = get_bb_snapshot()
        if snap.get("facts") or snap.get("datasets"):
            return True
    except Exception:
        pass
    return False

# ----- 节点定义 -----

def supervisor_node(state: Dict[str, Any]):
    print("\n[Node] >>> Supervisor")
    _ensure_init(state)

    # ▼▼▼ 核心修改：使用 prompt_builder 获取 Prompt ▼▼▼
    supervisor_system_prompt = get_system_prompt("Supervisor")
    # ▲▲▲ 核心修改 ▲▲▲

    prompt = ChatPromptTemplate.from_messages([
        ("system", supervisor_system_prompt),
        ("placeholder", "{messages}"),
    ])
    msgs = _coerce_for_gemini(state["messages"])
    chain = prompt | llm.bind_tools(get_supervisor_tools())

    print("[Supervisor] Calling LLM...")
    out = chain.invoke({"messages": msgs})
    print(f"[Supervisor] LLM call returned. Action: {getattr(out, 'tool_calls', 'No action / Clarification')}")

    return {"messages": [out]}


def router_node(state: Dict[str, Any]):
    print("\n[Node] >>> Router")
    _ensure_init(state)
    result = route_and_execute(state)
    print(f"[Router] Finished execution. Returning {len(result.get('messages', []))} tool messages to Supervisor.")
    return result

def correction_node(state: Dict[str, Any]):
    """当 Supervisor 犯错时，此节点向其发送纠正指令。"""
    print("\n[Node] >>> Correction")
    correction_message = HumanMessage(
        content="[System Correction] Your last action was invalid (e.g., calling `final_answer` without evidence). "
                "Review the user's original request and the full conversation history. "
                "You MUST either delegate a task to an expert or, if the request is vague, ask a clarifying question."
    )
    return {"messages": [correction_message]}




def build_team_graph():
    """
    构建最终的、带有三段式策略开关的团队工作流图。
    """
    g = StateGraph(AgentState)

    g.add_node("Supervisor", supervisor_node)
    g.add_node("Router", router_node)
    g.add_node("Correction", correction_node)
    g.set_entry_point("Supervisor")

    def _cond(state: Dict[str, Any]):
        """
        这个函数是团队的大脑中枢，现在它会根据策略进行路由。
        """
        print("\n[Edge] Checking condition after Supervisor...")

        # ▼▼▼ 核心修改 1：从 state 中获取策略 ▼▼▼
        # 策略可以在 chat_cli.py 中设置
        policy = state.get("policy", "free")
        print(f"[Edge] Current policy is '{policy}'.")

        # ▲▲▲ 核心修改 1 ▲▲▲

        # 辅助函数，用于记录违规
        def _log_violation(kind: str, detail: Any):
            state.setdefault("violations", []).append(
                {"kind": kind, "detail": detail, "turn": state.get("turn_counter", 0)})

        msgs = state.get("messages") or [];
        if not msgs: return "Supervisor"
        last = msgs[-1]
        if not isinstance(last, AIMessage): return END

        tcs = getattr(last, "tool_calls", None)

        # 检查1：无证据就调用 final_answer
        if tcs and tcs[0].get("name") == "final_answer":
            if not _has_min_evidence(state):
                _log_violation("no_evidence_final_answer", {"content": tcs[0].get("args", {}).get("answer")})

                if policy == "strict":
                    print("[Edge] VIOLATION (strict): 'final_answer' without evidence. Routing to Correction.")
                    return "Correction"
                elif policy == "gentle":
                    print("[Edge] VIOLATION (gentle): 'final_answer' without evidence. Injecting hint and allowing.")
                    # 注入温和提醒，但仍然让它走向 END
                    state["messages"].append(HumanMessage(
                        content="[System Hint] You are calling final_answer without sufficient evidence on the blackboard. I will allow it this time for observation purposes."))
                    return END
                else:  # free
                    print("[Edge] VIOLATION (free): 'final_answer' without evidence. Allowing.")
                    return END
            else:
                print("[Edge] 'final_answer' called with evidence. Ending.")
                return END

        # 检查2：一次调用多个工具 (假设我们期望只有一个)
        if tcs and len(tcs) > 1:
            _log_violation("multiple_tool_calls", {"count": len(tcs), "tools": [t.get("name") for t in tcs]})

            if policy == "strict":
                print(f"[Edge] VIOLATION (strict): Attempted to call {len(tcs)} tools at once. Routing to Correction.")
                return "Correction"
            elif policy == "gentle":
                print(f"[Edge] VIOLATION (gentle): Attempted to call {len(tcs)} tools. Injecting hint and allowing.")
                state["messages"].append(HumanMessage(
                    content=f"[System Hint] You should only call one tool at a time, but I will allow all {len(tcs)} for observation."))
                return "Router"
            else:  # free
                print(f"[Edge] VIOLATION (free): Attempted to call {len(tcs)} tools. Allowing.")
                return "Router"

        # 正常路径
        if tcs and len(tcs) == 1:
            print(f"[Edge] Valid tool call '{tcs[0].get('name')}' detected, routing to Router.")
            return "Router"

        # 无工具调用路径
        print("[Edge] No tool call from Supervisor. Ending this turn.")
        return END

    g.add_conditional_edges("Supervisor", _cond,
                            {END: END, "Router": "Router", "Correction": "Correction", "Supervisor": "Supervisor"})
    g.add_edge("Router", "Supervisor")
    g.add_edge("Correction", "Supervisor")

    return g.compile()
