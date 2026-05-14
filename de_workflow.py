# de_workflow.py — ReAct 版（無 Supervisor），不動其他實驗
from __future__ import annotations
from typing import List, Dict, Any, Optional
import json
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage, BaseMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import StateGraph, END
from common import llm, AgentState
from metrics import note_tool_event, now_ms
import prompts
import os
from common import llm, AgentState, dbg, dbg_json
# 視你的工具集而定；若沒有 deliver_dataframe / semantic_select 也沒關係
# DATASET_TOOLS = {"sql_db_query", "deliver_dataframe", "sql_db_semantic_select"}
DATASET_TOOLS = {"sql_db_query", "deliver_dataframe", "sql_db_semantic_select", "sql_db_list_tables", "sql_db_schema", "pandas_transform"}

def _extract_text_content(msg: AIMessage) -> str:
    """把 AIMessage.content 轉成可讀字串：支援 str / list[dict] 兩種格式。"""
    c = getattr(msg, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for it in c:
            if isinstance(it, dict):
                # 常見型別：text / thought / explanation
                t = it.get("type")
                if t in ("text", "thought", "explanation"):
                    parts.append(it.get("text") or it.get("content") or "")
        return "\n".join(p for p in parts if p)
    # fallback
    return str(c)

def _last_human_snippet(state, n=300) -> str:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage):
            return (m.content or "")[:n]
    return ""

# -----------------------------
# 1) 建立 DE 執行器（不使用 ChatPromptTemplate，避免 {name} 解析錯誤）
# -----------------------------
def create_de_executor(mode: str, tools_for_agent: List, system_prompt: Optional[str] = None):
    """
    回傳一個 Runnable。
    ★★★ 兼容性修改 ★★★
    如果 system_prompt 被提供 (来自 Stage-2)，则使用它。
    否则，回退到 Stage-1 的默认行为 (从 prompts.py 加载)。
    """

    # ▼▼▼ 核心修改 ▼▼▼
    final_sys_text = ""
    if system_prompt:
        # 如果 Stage-2 传入了新的 prompt (角色卡)，就使用它
        final_sys_text = system_prompt
    else:
        # 否则，保持 Stage-1 的旧逻辑
        tool_names = ", ".join([t.name for t in tools_for_agent])
        if mode == "baseline":
            final_sys_text = prompts.DE_BASELINE_PROMPT.format(tool_names=tool_names)
        else:
            final_sys_text = prompts.DE_AUGMENTED_PROMPT.format(tool_names=tool_names)
    # ▲▲▲ 核心修改 ▲▲▲

    bound = llm.bind_tools(tools_for_agent)

    def _run(inp: Dict[str, Any], config=None):
        msgs = inp.get("messages") or []
        # 直接把【最终决定好】的 SystemMessage 放到最前
        full = [SystemMessage(content=final_sys_text), *msgs]
        return bound.invoke(full, config=config)

    return RunnableLambda(_run)

# -----------------------------
# 2) DE 節點：只負責讓 LLM 產生下一步（Think/Act）
# -----------------------------
def de_node(state: AgentState, agent_executor):
    print("\n[Node] >>> DataEngineer")
    snippet = _last_human_snippet(state)
    print("[DE][In] last human: %r" % snippet)

    from harness_callback import HarnessCallback
    res = agent_executor.invoke(
        {"messages": state["messages"]},
        config={"callbacks": [HarnessCallback(state, "DE")]},
    )

    # 兼容多種回傳型態
    msgs: list[BaseMessage] = []
    if isinstance(res, dict) and "messages" in res:
        msgs = res["messages"] or []
    elif isinstance(res, BaseMessage):
        msgs = [res]
    else:
        print(f"[DE][DEBUG] unexpected executor result type: {type(res)} -> {res!r}")

    found_any = False
    for msg in msgs:
        if isinstance(msg, AIMessage):
            found_any = True
            text = _extract_text_content(msg)
            print(f"[DE][Thought] {text if text else '(empty)'}")
            tcs = getattr(msg, "tool_calls", None) or []
            if tcs:
                print("[DE][Plan tools] " + ", ".join(f"{tc.get('name')}({tc.get('args')})" for tc in tcs))
            else:
                print("[DE][Plan tools] (none)")
    if not found_any:
        print("[DE][DEBUG] no AIMessage found to print Thought")

    return {"messages": msgs or ([res] if isinstance(res, BaseMessage) else [])}

def tool_node(state: AgentState, tool_map: Dict[str, Any]):
    AGENT_TAG = "[DE]"
    print(f"\n[Node:DE] >>> ToolExecutor")
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", []) if isinstance(last, AIMessage) else []
    if not tool_calls:
        return {}

    new_msgs: List[ToolMessage] = []
    state.setdefault("tool_events", [])

    for tc in tool_calls:
        name = tc.get("name")
        args = tc.get("args") or {}
        if name not in tool_map:
            print(f"{AGENT_TAG} [Tool] (skip) unknown tool: {name}")
            note_tool_event(
                state,
                tool_name=name or "UNKNOWN",
                args=args,
                started_ms=now_ms(),
                latency_ms=0,
                raw_output=json.dumps({"status": "error", "error": "unknown_tool"}, ensure_ascii=False),
            )
            continue

        fn = tool_map[name]
        print(f"{AGENT_TAG} [Tool] -> {name} args={repr(args)[:300]}")

        started = now_ms()
        try:
            # LangChain StructuredTool 建議用 .invoke(dict)
            raw = fn.invoke(args if isinstance(args, dict) else {})
        except Exception as e:
            raw = {"status": "error", "error": f"{type(e).__name__}: {e}"}
        latency = now_ms() - started

        # --- 正規化輸出 ---
        if isinstance(raw, (dict, list)):
            raw_obj = raw
            try:
                raw_text = json.dumps(raw, ensure_ascii=False)
            except Exception:
                raw_text = str(raw)
        elif isinstance(raw, (bytes, bytearray)):
            try:
                raw_text = raw.decode(errors="ignore")
            except Exception:
                raw_text = str(raw)
            try:
                raw_obj = json.loads(raw_text)
            except Exception:
                raw_obj = {}
        else:
            raw_text = str(raw)
            try:
                raw_obj = json.loads(raw_text)
            except Exception:
                raw_obj = {}

        head = (raw_text or "")[:1000].replace("\n", " ")
        print(f"{AGENT_TAG} [Tool] <- {name} {latency}ms head={head}")

        # metrics
        note_tool_event(
            state, tool_name=name, args=args,
            started_ms=started, latency_ms=latency, raw_output=raw_text
        )

        # 回對話
        new_msgs.append(
            ToolMessage(content=raw_text, name=name, tool_call_id=tc.get("id", "tool_call"))
        )

        if name == "deliver_dataframe":
            state["phase"] = "DE:deliver"

    return {"messages": new_msgs, "tool_events": state.get("tool_events", [])}


# -----------------------------
# 4) 路由（ReAct）：DE → Tool 或 DS；Tool → DE 或 DS
# -----------------------------
_MAX_TURNS = 8  # 迭代保險絲，避免無限迴圈

def _has_successful_delivery(state: AgentState) -> bool:
    metrics = state.get("metrics", {}) or {}
    if metrics.get("deliver_via"):
        return True

    for msg in reversed(state.get("messages", [])):
        if not isinstance(msg, ToolMessage):
            continue
        if (getattr(msg, "name", "") or "") != "deliver_dataframe":
            continue
        try:
            payload = json.loads(msg.content)
        except Exception:
            payload = {}
        if isinstance(payload, dict) and payload.get("status") == "ok":
            return True
    return False

def router_after_de(state: AgentState):
    """DE 輸出後：若有 tool_calls → 去執行工具；否則直接進 DS（失敗/成功由 DS 定義）"""
    m = state.setdefault("metrics", {})
    m["de_turns"] = int(m.get("de_turns", 0)) + 1
    if m["de_turns"] > _MAX_TURNS:
        return "DataScientistValidator"

    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "ToolExecutor"
    if _has_successful_delivery(state):
        return "DataScientistValidator"
    # 沒有工具呼叫 → 讓 DS 判定（通常視為 no_result_found）
    return "DataEngineer"

def router_after_tool(state: AgentState):
    """
    工具完成後：
    - 若是資料集工具且輸出看起來有效且 rowcount >= min_rows → 交給 DS
    - 否則回到 DE 讓它根據 Observation 做下一步
    """
    last = state["messages"][-1]
    if not isinstance(last, ToolMessage):
        return "DataEngineer"

    name = getattr(last, "name", "") or ""
    # 非資料工具：例如列表/查 schema，回 DE 繼續思考
    if name not in DATASET_TOOLS:
        return "DataEngineer"

    # 嘗試解析工具輸出
    try:
        # 如果是交付檔案（parquet 路徑），直接交給 DS
        if isinstance(last.content, str) and last.content.endswith(".parquet"):
            state.setdefault("metrics", {})["deliver_via"] = "pandas"
            return "DataScientistValidator"

        payload = json.loads(last.content)
        if payload.get("status") != "ok":
            return "DataEngineer"

        contract = state.get("task_contract") or {}
        min_rows = int(contract.get("min_rows", 1))
        if int(payload.get("rowcount", 0)) >= min_rows:
            state.setdefault("metrics", {})["deliver_via"] = "sql"
            return "DataScientistValidator"
        return "DataEngineer"
    except Exception:
        return "DataEngineer"

# -----------------------------
# 5) 建圖
# -----------------------------
def build_graph(agent_state_cls, de_executor, tool_map):
    print(f"[DEBUG] RUN_ID={os.getenv('RUN_ID')}")
    g = StateGraph(agent_state_cls)
    g.add_node("DataEngineer", lambda s: de_node(s, de_executor))
    g.add_node("ToolExecutor", lambda s: tool_node(s, tool_map))

    g.set_entry_point("DataEngineer")
    g.add_conditional_edges("DataEngineer", router_after_de, {
        "ToolExecutor": "ToolExecutor",
        "DataScientistValidator": END,
    })
    g.add_conditional_edges("ToolExecutor", router_after_tool, {
        "DataEngineer": "DataEngineer",
        "DataScientistValidator": END,
    })
    return g.compile()

