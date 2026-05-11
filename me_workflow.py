# me_workflow.py (整合 Grok 建議的完整最終版)
import os, json, time, traceback, re, warnings
from typing import Dict, Any, List, Optional
from collections import Counter
from bb_tools import bb_add_citations, bb_add_facts
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from common import dbg, dbg_json
import me_tools
from metrics import init_metrics, note_tool_event, finalize_metrics, update_me_citation_metrics, _ensure_metrics
from common import llm, AgentState, run_and_log_experiment

# 忽略来自 LangChain 底层的、与 Pydantic 相关的 UserWarning
# import warnings, prompts
import warnings

warnings.filterwarnings("ignore", message=".*'additionalProperties' is not supported in schema.*")

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

def create_me_executor(mode: str, tools: List, system_prompt: Optional[str] = None):
    """
    ★★★ 兼容性修改 ★★★
    如果 system_prompt 被提供 (来自 Stage-2)，则使用它。
    否则，回退到 Stage-1 的默认行为 (使用本文件中定义的 ME_AGENTIC_SYS)。
    """

    final_sys_prompt_text = ""
    if system_prompt:
        # 如果 Stage-2 传入了新的 prompt (角色卡)，就使用它
        final_sys_prompt_text = system_prompt
    # else:
    #     # 否则，保持 Stage-1 的旧逻辑
    #     # 假设 prompts.py 中没有 ME 的 prompt，我们从本文件加载
    #     # 如果您的 prompts.py 中有，请取消下面的注释
    #     # import prompts
    #     final_sys_prompt_text = prompts.ME_AGENTIC_SYS

    # 后续的绑定逻辑保持不变
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=final_sys_prompt_text),
        ("placeholder", "{messages}")
    ])

    return prompt | llm.bind_tools(tools)

def ME_node(state: AgentState, executor):
    from llm_harness import SelfEvaluator
    print("\n[Node] >>> MachineExpert")
    snippet = _last_human_snippet(state)
    print("[ME][In] last human: %r" % snippet)

    from harness_callback import HarnessCallback
    res = executor.invoke(state, config={"callbacks": [HarnessCallback(state, "ME")]})

    # 兼容：有些 executor 直接回 dict，有些回單一 AIMessage
    msgs: list[BaseMessage] = []
    if isinstance(res, dict) and "messages" in res:
        msgs = res["messages"] or []
    elif isinstance(res, BaseMessage):
        msgs = [res]
    else:
        print(f"[ME][DEBUG] unexpected executor result type: {type(res)} -> {res!r}")

    # 掃描所有 AIMessage，把 Thought 與 ToolCalls 印出來
    found_any = False
    last_ai_text = ""
    for msg in msgs:
        if isinstance(msg, AIMessage):
            found_any = True
            text = _extract_text_content(msg)
            last_ai_text = text or last_ai_text
            print(f"[ME][Thought] {text if text else '(empty)'}")
            tcs = getattr(msg, "tool_calls", None) or []
            if tcs:
                formatted = ", ".join(f"{tc.get('name')}({tc.get('args')})" for tc in tcs)
                print("[ME][Plan tools] " + formatted)
            else:
                print("[ME][Plan tools] (none)")
    if not found_any:
        print("[ME][DEBUG] no AIMessage found to print Thought")

    # SelfEvaluator（非阻塞）
    if last_ai_text and not getattr(executor, "_skip_self_eval", False):
        try:
            from common import llm as _llm
            SelfEvaluator().evaluate(_llm, last_ai_text, "ME", state)
        except Exception:
            pass

    # 回寫訊息到狀態
    return {"messages": msgs or [res] if isinstance(res, BaseMessage) else []}


# me_workflow.py 內的 Tool_node（節錄：包含黑板寫入與安全檢查）
def Tool_node(state: AgentState, tool_map: Dict[str, Any]):
    print("\n[Node:ME] >>>  ToolExecutor")
    last = state["messages"][-1]
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {}

    tool_messages: List[ToolMessage] = []
    state.setdefault("hits", [])
    state.setdefault("tool_events", [])

    just_read_chunks = 0  # 記錄本輪是否有新讀取
    for tc in last.tool_calls:
        name = tc.get("name")
        args = tc.get("args", {})
        if name not in tool_map:
            continue

        # === 這一行是在「呼叫工具之前」印計畫 ===
        print(f"[Tool] -> {name} args={repr(args)[:300]}")

        started = int(time.time() * 1000)
        try:
            raw = tool_map[name].invoke(args)
        except Exception as e:
            raw = json.dumps({"status": "error", "error": str(e)})
        latency = int(time.time() * 1000) - started

        # --- 安全正規化：將 raw 轉為字串，避免 metrics 對非字串做切片而崩潰 ---
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

        note_tool_event(
            state,
            tool_name=name,
            args=args,
            started_ms=started,
            latency_ms=latency,
            raw_output=raw_text,
        )

        tool_messages.append(
            ToolMessage(content=raw_text, name=name, tool_call_id=tc.get("id", name))
        )

        if name == "synthesize_and_cite":
            state["phase"] = "ME:synthesize"

        # 聚合 hits
        obj = raw_obj if isinstance(raw_obj, (dict, list)) else (raw_obj or {})
        if name == "initial_search":
            for h in (obj.get("candidates") or []):
                key = (h.get("doc_id"), int(h.get("page", 0)))
                if not any((x.get("doc_id"), x.get("page")) == key for x in state["hits"]):
                    state["hits"].append({
                        "doc_id": h.get("doc_id"),
                        "page": int(h.get("page", 0)),
                        "score": h.get("score", 0.0)
                    })
        elif name == "read_document_chunk":
            ch = (obj.get("chunk") or {})
            if ch:
                key = (ch.get("doc_id"), int(ch.get("page", 0)))
                merged = False
                for x in state["hits"]:
                    if (x.get("doc_id"), x.get("page")) == key:
                        x["chunk"] = ch
                        merged = True
                        break
                if not merged:
                    state["hits"].append({
                        "doc_id": ch.get("doc_id"),
                        "page": int(ch.get("page", 0)),
                        "score": 0.0,
                        "chunk": ch
                    })
                just_read_chunks += 1

    # ===== 強制合成邏輯（Stage-2 Ready）=====
    filled = [h for h in state.get("hits", []) if (h.get("chunk") or {}).get("text")]
    tool_counts = Counter(ev.get("tool") for ev in state.get("tool_events", []))
    recent = [ev.get("tool") for ev in state.get("tool_events", [])][-3:]
    repeated = len(recent) == 3 and len(set(recent)) == 1
    used_synth = tool_counts.get("synthesize_and_cite", 0) > 0
    total_calls = len(state.get("tool_events", []))

    should_synth = False
    if len(filled) >= 1 and not used_synth:
        if just_read_chunks > 0 or repeated or total_calls >= 5:
            should_synth = True

    if should_synth and "synthesize_and_cite" in tool_map:
        # 取第一個 HumanMessage 當 question
        q = ""
        for m in state.get("messages", []):
            if isinstance(m, HumanMessage):
                mt = re.search(r"問題:\s*(.+)", m.content or "")
                q = (mt.group(1).strip() if mt else (m.content or "").strip())
                break

        forced_raw = tool_map["synthesize_and_cite"].invoke({"question": q, "hits": filled})

        # 同樣做安全正規化（避免合成工具回 dict/bytes）
        if isinstance(forced_raw, (dict, list)):
            try:
                forced_text = json.dumps(forced_raw, ensure_ascii=False)
            except Exception:
                forced_text = str(forced_raw)
        elif isinstance(forced_raw, (bytes, bytearray)):
            try:
                forced_text = forced_raw.decode(errors="ignore")
            except Exception:
                forced_text = str(forced_raw)
        else:
            forced_text = str(forced_raw)

        tool_messages.append(ToolMessage(
            content=forced_text, name="synthesize_and_cite", tool_call_id="forced_synth"
        ))
        state["phase"] = "ME:synthesize"

        # ✅ 新增：把合成結構化輸出寫入黑板（citations / facts）
        try:
            payload = json.loads(forced_text) if isinstance(forced_text, str) else {}
        except Exception:
            payload = {}

        cits = payload.get("citations") or payload.get("envelope", {}).get("citations") or []
        facts = payload.get("facts") or payload.get("envelope", {}).get("facts") or []

        # 容錯：若只有含頁碼的文字，簡單抽最低限度 citation，如 "[control_loops.md p.1]"
        if not cits and isinstance(payload.get("cited_answer") or payload.get("envelope", {}).get("answer"), str):
            ans = payload.get("cited_answer") or payload.get("envelope", {}).get("answer")
            m = re.findall(r"\[([^\]\n]+?)\s+p\.?(\d+)\]", ans or "", flags=re.I)
            cits = [{"doc_id": a.strip(), "page": int(b)} for a, b in m]

        # 落盤到黑板（以 RUN_ID 分區）
        run_id = os.getenv("RUN_ID")
        try:
            if cits:
                bb_add_citations(run_id, cits)
            if facts:
                bb_add_facts(run_id, facts, agent="ME", source_tool="synthesize_and_cite")
        except Exception:
            pass

    return {
        "messages": tool_messages,
        "hits": state.get("hits", []),
        "tool_events": state.get("tool_events", []),   # 關鍵：一定回寫
    }




def route(state: AgentState):
    if len(state.get("tool_events", [])) >= 10:
        print("[WARN] 已達到最大工具調用次數限制 (10)，強制結束。")
        return "End"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "Tool"
    return "End"

def build_me_graph(mode: str, executor, tool_map):
    g = StateGraph(AgentState)
    g.add_node("ME", lambda s: ME_node(s, executor))
    g.add_node("Tool", lambda s: Tool_node(s, tool_map))
    g.set_entry_point("ME")
    g.add_conditional_edges("ME", route, {"Tool": "Tool", "End": END})
    g.add_edge("Tool", "ME")
    return g.compile()

def run_me_batch(mode: str, tasks: List[str], pdf_dir: str, repeats: int = 1):
    try:
        used_cache = me_tools.init_me_index_from_dir(pdf_dir)
        print(f"[RAG] Index cache: {'HIT' if used_cache else 'BUILD'} @ {pdf_dir}")
        if me_tools.DOC_INDEX is None or not getattr(me_tools.DOC_INDEX, "pages", None):
            raise RuntimeError("Sanity check failed: Index object invalid or empty.")
        allowed_docs = sorted({p.doc_id for p in me_tools.DOC_INDEX.pages})
        print(f"[INFO] Index ready. Found {len(allowed_docs)} documents: {allowed_docs}")
    except Exception as e:
        print("\nCRITICAL: RAG INDEX INITIALIZATION FAILED:", e)
        traceback.print_exc()
        return

    tools, tool_map = me_tools.get_me_tools(mode)
    executor = create_me_executor(mode, tools)
    graph = build_me_graph(mode, executor, tool_map)

    for i, question in enumerate(tasks, start=1):
        for r in range(1, repeats + 1):
            run_id = f"exp1.2_{mode}_t{i}_r{r}_{time.strftime('%Y%m%d_%H%M%S')}"
            initial_content = f"問題: {question}\n\n可用文件: {', '.join(allowed_docs)}"
            state: AgentState = {
                "messages": [HumanMessage(content=initial_content)],
                "metrics": {},
                "tool_events": [],
                "hits": [],
            }
            init_metrics(state, schema_snapshot=None)
            run_and_log_experiment(graph, state, run_id, recursion_limit=50)
            time.sleep(1)

    return graph
