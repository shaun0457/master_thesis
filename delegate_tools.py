import json
import inspect
import uuid, os as _os
from langchain_core.messages import HumanMessage, AIMessage
from prompt_builder import get_system_prompt
from common import bb_snapshot_text, set_global_seeds, get_seed
from run_logger import get_run_logger, note_tool_call, emit_bb_write, emit_bb_read, emit_event, emit_compliance
import os, datetime
from typing import Dict, Any, Tuple, List, Literal, Optional
from pydantic import BaseModel, Field
from langchain.tools import tool
from run_logger import get_run_logger, note_tool_call, emit_bb_write, emit_bb_read
import bb_tools
import time
from metrics import note_tool_event
from run_logger import emit_bb_write, emit_bb_read, note_tool_call

POLICY = 'minimal'


# ---------------------------------------------------------------------------
# Plan D: ME → BB structured fault facts write
# ---------------------------------------------------------------------------

def _extract_and_write_me_fault_facts(out_state: dict) -> None:
    """Scan ME subgraph ToolMessages for kg_query_fault results; write structured facts to BB."""
    from langchain_core.messages import ToolMessage
    run_id = os.environ.get("RUN_ID")
    for msg in out_state.get("messages", []):
        if not (isinstance(msg, ToolMessage) and getattr(msg, "name", "") == "kg_query_fault"):
            continue
        try:
            data = json.loads(msg.content)
            fault_id = data.get("fault_id")
            if fault_id is None:
                continue
            sensors = data.get("diagnostic_sensors", [])
            sensor_cols = ", ".join(s["column"] for s in sensors if isinstance(s, dict))
            structured = {
                "agent": "ME",
                "source_tool": "kg_query_fault",
                "fault_id": fault_id,
                "description": data.get("description", ""),
                "diagnostic_sensors": sensors,
                "claim": (
                    f"IDV_{fault_id}: {data.get('description', '')}."
                    + (f" Diagnostic sensors: {sensor_cols}" if sensor_cols else "")
                ),
            }
            bb_tools.bb_add_facts(
                run_id=run_id,
                facts=[structured],
                agent="ME",
                source_tool="kg_query_fault",
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Plan B: DE reads ME fault facts for context injection
# ---------------------------------------------------------------------------

def _read_me_fault_facts() -> str:
    """Read ME-written kg_query_fault facts from BB. Returns formatted string or ''."""
    run_id = os.environ.get("RUN_ID")
    if not run_id:
        return ""
    try:
        reg = bb_tools._load(run_id)
        me_facts = [
            f for f in reg.get("facts", [])
            if isinstance(f, dict)
            and f.get("agent") == "ME"
            and f.get("source_tool") == "kg_query_fault"
        ]
        if not me_facts:
            return ""
        lines = []
        for f in me_facts:
            sensors = [s["column"] for s in f.get("diagnostic_sensors", []) if isinstance(s, dict)]
            lines.append(f"- IDV_{f['fault_id']}: {f.get('description', '')}")
            if sensors:
                lines.append(f"  → query these sensors: {', '.join(sensors)}"
                             f" with faultnumber={f['fault_id']}")
                lines.append("  → use deliver_dataframe (NOT just COUNT)")
        return "\n".join(lines)
    except Exception:
        return ""


def _format_task_contract(task_text: str, success_criteria: Optional[str] = None) -> str:
    """Build a [TASK CONTRACT] block so the sub-agent knows what 'done' looks like."""
    lines = ["[TASK CONTRACT]", f"Task: {task_text.strip()}"]
    if success_criteria and success_criteria.strip():
        lines.append(f"Success criteria: {success_criteria.strip()}")
    return "\n".join(lines)


def _format_bb_index(blackboard: dict) -> str:
    """Produce a compact [BLACKBOARD INDEX] summary of current blackboard state."""
    facts = (blackboard or {}).get("facts", [])
    datasets = (blackboard or {}).get("datasets", [])
    open_issues = (blackboard or {}).get("open_issues", [])
    if not facts and not datasets:
        return "[BLACKBOARD INDEX]\n  (empty — no evidence yet)"
    lines = ["[BLACKBOARD INDEX]"]
    for f in facts:
        if isinstance(f, dict):
            agent = f.get("agent", "?")
            conf = f.get("confidence", 1.0)
            claim = f.get("claim", "")
            lines.append(f"  [{agent}/conf:{conf:.2f}] {claim}")
        else:
            lines.append(f"  {f}")
    for d in datasets:
        lines.append(f"  [dataset] {d}")
    if open_issues:
        lines.append(f"  open_issues: {open_issues}")
    return "\n".join(lines)


_ADDITIVE_METRICS = {
    "llm_calls_total", "tokens_in_total", "tokens_out_total",
    "llm_latency_ms_sum", "tool_calls_total", "cache_hits",
}


def _merge_metrics(parent: dict, child: dict) -> dict:
    """Merge child metrics into parent — additive for numeric counters, overwrite for strings."""
    for k, v in child.items():
        if k in _ADDITIVE_METRICS and isinstance(v, (int, float)):
            parent[k] = parent.get(k, 0) + v
        else:
            parent[k] = v
    return parent


def _topic_from(state: Dict[str, Any], explicit: Optional[str] = None) -> str:
    if explicit: return explicit
    return (state.get("topic_ctx") or {}).get("topic_id", "") or state.get("topic_id", "")

def _owner_from(state: Dict[str, Any], explicit: Optional[str] = None) -> str:
    if explicit: return explicit
    return (state.get("topic_ctx") or {}).get("owner", "") or state.get("owner", "")

def _run_id_from(state: Dict[str, Any]) -> str:
    return str(state.get("RUN_ID") or os.environ.get("RUN_ID") or "unknown_run")


class _TopicCtx:
    """把 topic_id/owner 暫存到 state['topic_ctx']，離開時還原"""
    def __init__(self, state: Dict[str, Any], topic_id: Optional[str], owner: Optional[str]):
        self.state = state
        self.topic_id = topic_id
        self.owner = owner
        self.prev = dict(state.get("topic_ctx") or {})

    def __enter__(self):
        ctx = self.state.setdefault("topic_ctx", {})
        if self.topic_id: ctx["topic_id"] = self.topic_id
        if self.owner:    ctx["owner"] = self.owner
        return ctx

    def __exit__(self, exc_type, exc, tb):
        if self.prev:
            self.state["topic_ctx"] = self.prev
        else:
            self.state.pop("topic_ctx", None)


def make_p2p_tools(state: dict, agent_name: str) -> Tuple[List, List]:
    """
    建立 P2P 工具（含 request_delegate）並回傳 (tools, p2p_req_box)
    - tools: 要注入到該 agent 子圖的工具清單
    - p2p_req_box: 本輪子圖蒐集到的委派請求（Router 會在子圖結束後消化）
    """
    rl = get_run_logger()
    p2p_req_box: List[Dict[str, Any]] = []

    @tool("request_delegate")
    def request_delegate(to: str, task: str) -> str:
        """Record a peer-to-peer delegate request; Supervisor/Router may pick it up."""
        to_norm = (to or "").strip().upper()
        if to_norm not in {"DS", "DE", "ME"}:
            return "Error: 'to' must be one of DS/DE/ME."
        p2p_req_box.append({"to": to_norm, "task": task})

        # 記「私訊」事件，供 ETL 統計 side-channel / 私訊委派
        try:
            emit_event({
                "event_type": "message",
                "agent": agent_name,
                "addressed_to": to_norm,
                "channel": "private",
                "topic_id": (state.get("topic_ctx") or {}).get("topic_id") or state.get("topic_id") or "",
                "turn_index": int(state.get("turn_counter") or 0),
                "content_text": (task or "")[:800],
            }, state=state)
        except Exception:
            pass

        # 操守量測：side-channel +1
        try:
            emit_compliance(state=state, side_channel_increment=1)
        except Exception:
            pass

        #（相容）也可記到 legacy tool_events
        try:
            state.setdefault("tool_events", []).append({
                "ts": datetime.datetime.now().isoformat(),
                "agent": agent_name,
                "tool": "request_delegate",
                "ok": True,
                "args": {"to": to_norm, "task": task}
            })
        except Exception:
            pass

        return f"Request to delegate to '{to_norm}' recorded."

    return [request_delegate], p2p_req_box


def attach_delegate_requests(result: Dict[str, Any], p2p_box: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把本輪子圖收集的委派請求裝回回傳物件，不改動其他欄位。"""
    out = dict(result or {})
    if p2p_box:
        out["delegate_requests"] = list(p2p_box)
    return out


# def make_blackboard_tools(state: Dict[str, Any], agent_name: str) -> Tuple[List, List]:
#     """
#     工廠：建立綁定 state/agent 的黑板工具
#     - 保留 rl.tool_exec 與 in-memory blackboard (_bb(state))
#     - 鏡射到中心化 bb_tools（產生 artifact_id），並打點 emit_bb_write / emit_bb_read
#     - 注意：不再在這裡提供 request_delegate（改由 delegate_tools.make_p2p_tools 注入）
#     """
#     # —— helpers：從 state 取 topic/owner（Router 會在 args 塞到 state['topic_ctx']）——
#     def _topic_id(explicit: Optional[str] = None) -> str:
#         if explicit:
#             return explicit
#         return ((state.get("topic_ctx") or {}).get("topic_id")
#                 or state.get("topic_id") or "")
#
#     def _owner(explicit: Optional[str] = None) -> str:
#         if explicit:
#             return explicit
#         return ((state.get("topic_ctx") or {}).get("owner")
#                 or state.get("owner") or "")
#
#     rl = get_run_logger()
#
#     def _bb(st: Dict[str, Any]) -> Dict[str, Any]:
#         st.setdefault("blackboard", {})
#         bb = st["blackboard"]
#         for k in ("facts", "datasets", "citations", "open_issues"):
#             bb.setdefault(k, [])
#         return bb
#
#     @tool("read_blackboard")
#     def read_blackboard(
#         keys: List[Literal["facts", "datasets", "citations", "open_issues"]] = None,
#         limit: int = 3
#     ) -> dict:
#         """Reads sections from blackboard (instrumented + emit_bb_read)."""
#         rl = get_run_logger()
#         sel_keys = keys or ["datasets", "facts", "citations"]
#         with rl.tool_exec(
#             agent=agent_name, tool="read_blackboard",
#             task_id=os.getenv("TASK_ID"),
#             args={"keys": sel_keys, "limit": limit}
#         ) as t:
#             bb = _bb(state)
#
#             def _head(xs): return list(reversed(xs))[: int(limit or 3)]
#             res = {}
#             for k in sel_keys:
#                 items = _head(bb.get(k, []))
#                 res[k] = items
#                 fx_ids = [it.get("artifact_id") for it in items
#                           if isinstance(it, dict) and it.get("artifact_id")]
#                 if fx_ids:
#                     emit_bb_read(
#                         agent=agent_name,
#                         topic_id=_topic_id(),
#                         section=k,
#                         fact_ids_served=fx_ids,
#                         turn_index=state.get("turn_counter"),
#                         state=state
#                     )
#             note_tool_call(agent=agent_name, tool_name="read_blackboard", ok=True,
#                            latency_ms=None, args_head=f"keys={sel_keys},limit={limit}",
#                            topic_id=_topic_id(), state=state,
#                            turn_index=state.get("turn_counter"))
#             t.ok(True)
#
#         state.setdefault("tool_events", []).append({
#             "ts": datetime.datetime.now().isoformat(),
#             "agent": agent_name, "tool": "read_blackboard", "ok": True,
#             "args": {"keys": sel_keys, "limit": limit}
#         })
#         return res
#
#     class WriteToBlackboardArgs(BaseModel):
#         section: Literal["facts", "datasets", "citations", "open_issues"]
#         summary: str
#         content: Dict[str, Any]
#
#     @tool("write_to_blackboard", args_schema=WriteToBlackboardArgs)
#     def write_to_blackboard(section: str, summary: str, content: Dict[str, Any]) -> str:
#         """Write entry to blackboard (instrumented + mirror to central bb + emit_bb_write)."""
#         with rl.tool_exec(
#                 agent=agent_name,
#                 tool="write_to_blackboard",
#                 task_id=os.getenv("TASK_ID"),
#                 args={"summary": summary, **(content or {})},
#                 section=section
#         ) as t:
#             # A) 參數檢核（保持你原本規則）
#             if section == "datasets" and "df_payload" not in (content or {}):
#                 t.ok(False)
#                 state.setdefault("tool_events", []).append({
#                     "ts": datetime.datetime.now().isoformat(),
#                     "agent": agent_name,
#                     "tool": "write_to_blackboard",
#                     "ok": False,
#                     "args": {"section": section, "summary": summary}
#                 })
#                 return "Error: A 'datasets' entry MUST contain 'df_payload' with the file path."
#
#             # B) 先寫入 in-memory 黑板（相容）
#             bb = _bb(state)
#             record = {
#                 "agent": agent_name,
#                 "summary": summary,
#                 "timestamp": datetime.datetime.now().isoformat(),
#                 **(content or {})
#             }
#             bb.setdefault(section, []).append(record)
#
#             # C) 鏡射到中心化 bb_tools，取得 artifact_id（核心）
#             run_id = (state.get("run_id")
#                       or state.get("RUN_ID")
#                       or os.environ.get("RUN_ID")
#                       or "")
#             maybe_uri = (content or {}).get("df_payload", "") if section == "datasets" else (content or {}).get("uri",
#                                                                                                                 "")
#
#             artifact_id = None
#             try:
#                 out = bb_tools.bb_write(
#                     run_id=run_id,
#                     topic_id=_topic_id(),
#                     section=section,
#                     content_preview=summary,
#                     created_by=agent_name,
#                     uri=maybe_uri,
#                     intended_owner=_owner()
#                 )
#                 artifact_id = (out or {}).get("artifact_id")
#             except Exception as e:
#                 # 鏡射失敗不阻斷主流程；但回傳訊息裡會看得到
#                 pass
#
#             if artifact_id:
#                 record["artifact_id"] = artifact_id
#
#             # D) 原有產物登錄（保留）
#             try:
#                 if section == "datasets" and "df_payload" in (content or {}):
#                     rl.artifact(
#                         task_id=os.getenv("TASK_ID") or "",
#                         type_="dataset",
#                         path_or_hash=(content or {}).get("df_payload"),
#                         preview_stats={"summary": summary}
#                     )
#                 if section == "open_issues":
#                     rl.open_issue(
#                         by=agent_name,
#                         owner=(content or {}).get("owner", _owner() or "DE"),
#                         summary=summary,
#                         severity=(content or {}).get("severity", "blocking")
#                     )
#             except Exception:
#                 pass
#
#             # E) 打點
#             note_tool_call(agent=agent_name, tool_name="write_to_blackboard", ok=True,
#                            latency_ms=None, args_head=f"{section}:{summary[:80]}",
#                            topic_id=_topic_id(), state=state, turn_index=state.get("turn_counter"))
#             if artifact_id:
#                 emit_bb_write(agent=agent_name, topic_id=_topic_id(), section=section,
#                               artifact_id=artifact_id, uri=maybe_uri,
#                               intended_owner=_owner(), turn_index=state.get("turn_counter"),
#                               state=state)
#
#             t.ok(True)
#
#         # 兼容舊版：同步寫入 state["tool_events"]
#         state.setdefault("tool_events", []).append({
#             "ts": datetime.datetime.now().isoformat(),
#             "agent": agent_name,
#             "tool": "write_to_blackboard",
#             "ok": True,
#             "args": {"section": section, "summary": summary}
#         })
#         return f"Successfully wrote to blackboard section '{section}'."
#
#     # ✅ 只回傳 read / write；不再回傳 request_delegate
#     return [read_blackboard, write_to_blackboard], []

def make_blackboard_tools(state: Dict[str, Any], agent_name: str) -> Tuple[List, List]:
    """
    建立黑板工具 + P2P 委派工具（request_delegate）。
    回傳：(tools_list, p2p_req_box)
    - tools_list 會被注入子圖
    - p2p_req_box 收集本回合的 P2P 委派，回合結束由上層統一記成 delegate 事件
    """
    rl = get_run_logger()

    # ---- helpers ----
    def _bb(st: Dict[str, Any]) -> Dict[str, Any]:
        st.setdefault("blackboard", {})
        bb = st["blackboard"]
        for k in ("facts", "datasets", "citations", "open_issues"):
            bb.setdefault(k, [])
        return bb

    def _topic_id(explicit: Optional[str] = None) -> str:
        if explicit: return explicit
        return ((state.get("topic_ctx") or {}).get("topic_id")
                or state.get("topic_id") or "")

    def _owner(explicit: Optional[str] = None) -> str:
        if explicit: return explicit
        return ((state.get("topic_ctx") or {}).get("owner")
                or state.get("owner") or "")

    p2p_req_box: List[Dict[str, Any]] = []

    # ---------------- READ ----------------
    @tool("read_blackboard")
    def read_blackboard(
        keys: List[Literal["facts", "datasets", "citations", "open_issues"]] = None,
        limit: int = 3
    ) -> dict:
        """Reads sections from blackboard (instrumented + emit_bb_read)."""
        sel_keys = keys or ["datasets", "facts", "citations"]
        with rl.tool_exec(agent=agent_name, tool="read_blackboard",
                          task_id=os.getenv("TASK_ID"),
                          args={"keys": sel_keys, "limit": limit}) as t:
            bb = _bb(state)

            def _head(xs):
                return list(reversed(xs))[: int(limit or 3)]

            res = {}
            for k in sel_keys:
                items = _head(bb.get(k, []))
                res[k] = items
                fx_ids = [it.get("artifact_id") for it in items
                          if isinstance(it, dict) and it.get("artifact_id")]
                if fx_ids:
                    emit_bb_read(
                        agent=agent_name,
                        topic_id=_topic_id(),
                        section=k,
                        fact_ids_served=fx_ids,
                        turn_index=state.get("turn_counter"),
                        state=state
                    )
            note_tool_call(agent=agent_name, tool_name="read_blackboard", ok=True,
                           latency_ms=None, args_head=f"keys={sel_keys},limit={limit}",
                           topic_id=_topic_id(), state=state,
                           turn_index=state.get("turn_counter"))
            t.ok(True)
        state.setdefault("tool_events", []).append({
            "ts": datetime.datetime.now().isoformat(),
            "agent": agent_name, "tool": "read_blackboard", "ok": True,
            "args": {"keys": sel_keys, "limit": limit}
        })
        return res

    # ---------------- WRITE ----------------
    class WriteToBlackboardArgs(BaseModel):
        section: Literal["facts", "datasets", "citations", "open_issues"] = Field(..., description="The section to write.")
        summary: str = Field(..., description="Concise summary.")
        content: Dict[str, Any] = Field(..., description="Detail payload (e.g., df_payload for datasets).")

    @tool("write_to_blackboard", args_schema=WriteToBlackboardArgs)
    def write_to_blackboard(section: str, summary: str, content: Dict[str, Any]) -> str:
        """Write entry (instrumented + mirror to bb_tools + emit_bb_write)."""
        with rl.tool_exec(agent=agent_name, tool="write_to_blackboard",
                          task_id=os.getenv("TASK_ID"),
                          args={"summary": summary, **(content or {})},
                          section=section) as t:
            # A) 檢核
            if section == "datasets" and "df_payload" not in (content or {}):
                t.ok(False)
                state.setdefault("tool_events", []).append({
                    "ts": datetime.datetime.now().isoformat(),
                    "agent": agent_name, "tool": "write_to_blackboard", "ok": False,
                    "args": {"section": section, "summary": summary}
                })
                return "Error: 'datasets' entry MUST contain 'df_payload'."

            # B) in-memory
            bb = _bb(state)
            record = {
                "agent": agent_name,
                "summary": summary,
                "timestamp": datetime.datetime.now().isoformat(),
                **(content or {})
            }
            bb.setdefault(section, []).append(record)

            # C) 中央黑板鏡射（artifact_id）
            maybe_uri = (content or {}).get("df_payload", "") if section == "datasets" else (content or {}).get("uri", "")
            out = bb_tools.bb_write(
                run_id=state.get("run_id") or os.environ.get("RUN_ID", ""),
                topic_id=_topic_id(),
                section=section,
                content_preview=summary,
                created_by=agent_name,
                uri=maybe_uri,
                intended_owner=_owner()
            )
            artifact_id = out.get("artifact_id", "")
            record["artifact_id"] = artifact_id

            # D) 記錄與打點
            try:
                if section == "datasets" and "df_payload" in (content or {}):
                    rl.artifact(task_id=os.getenv("TASK_ID") or "", type_="dataset",
                                path_or_hash=(content or {}).get("df_payload"),
                                preview_stats={"summary": summary})
                if section == "open_issues":
                    rl.open_issue(by=agent_name,
                                  owner=(content or {}).get("owner", _owner() or "DE"),
                                  summary=summary,
                                  severity=(content or {}).get("severity", "blocking"))
            except Exception:
                pass

            note_tool_call(agent=agent_name, tool_name="write_to_blackboard", ok=True,
                           latency_ms=None, args_head=f"{section}:{summary[:80]}",
                           topic_id=_topic_id(), state=state,
                           turn_index=state.get("turn_counter"))
            emit_bb_write(agent=agent_name, topic_id=_topic_id(), section=section,
                          artifact_id=artifact_id, uri=maybe_uri,
                          intended_owner=_owner(),
                          turn_index=state.get("turn_counter"), state=state)
            t.ok(True)

        state.setdefault("tool_events", []).append({
            "ts": datetime.datetime.now().isoformat(),
            "agent": agent_name, "tool": "write_to_blackboard", "ok": True,
            "args": {"section": section, "summary": summary}
        })
        return f"Successfully wrote to blackboard section '{section}'."

    # ---------------- P2P 委派（★ 這就是你缺的工具） ----------------
    @tool("request_delegate")
    def request_delegate(to: str, task: str) -> str:
        """Record a peer-to-peer delegate request; Supervisor/Router may pick it up."""
        to_norm = (to or "").strip().upper()
        if to_norm not in {"DS", "DE", "ME"}:
            return "Error: 'to' must be one of DS/DE/ME."
        p2p_req_box.append({"to": to_norm, "task": task})

        with rl.tool_exec(agent=agent_name, tool="request_delegate",
                          task_id=os.getenv("TASK_ID"),
                          args={"to": to_norm, "task": task}) as t:
            t.ok(True)

        emit_event({
            "event_type": "message",
            "agent": agent_name,
            "addressed_to": to_norm,
            "channel": "private",
            "topic_id": _topic_id(),
            "turn_index": int(state.get("turn_counter") or 0),
            "content_head": (task or "")[:160]
        }, state=state)

        emit_compliance(state=state, side_channel_increment=1)

        state.setdefault("tool_events", []).append({
            "ts": datetime.datetime.now().isoformat(),
            "agent": agent_name, "tool": "request_delegate", "ok": True,
            "args": {"to": to_norm, "task": task}
        })
        return f"Request to delegate to '{to_norm}' recorded."

    # ✅ 回傳含有 request_delegate 的工具清單
    return [read_blackboard, write_to_blackboard, request_delegate], p2p_req_box


_GRAPH_CACHE = {}



# def _invoke_stage1(agent: str, intro_msgs: List[HumanMessage], extra_tools: List, state: Dict[str, Any]):
#     # 固定 policy 與取得角色卡
#     policy = POLICY
#     role_card_prompt = get_system_prompt(agent, policy)
#     prompt_hash = abs(hash(role_card_prompt)) & 0xFFFF
#     cache_key = f"{agent}_augmented_{policy}_{prompt_hash}"
#
#     # 建/取子圖執行器
#     if cache_key in _GRAPH_CACHE:
#         graph = _GRAPH_CACHE[cache_key]
#     else:
#         try:
#             from common import AgentState  # 你的專案內的 AgentState；如果沒有就 fallback
#         except ImportError:
#             AgentState = dict
#
#         tools_mod = __import__(f"{agent.lower()}_tools")
#         get_tools_func = getattr(tools_mod, f"get_{agent.lower()}_tools")
#         tools_stage1, tool_map = get_tools_func("augmented")
#         for t in extra_tools:
#             tool_map[t.name] = t
#
#
#         workflow_module_name = "ds_workflow_s2" if agent == "DS" else f"{agent.lower()}_workflow"
#         wf_mod = __import__(workflow_module_name)
#         create_exec_func = getattr(wf_mod, f"create_{agent.lower()}_executor")
#         build_graph_func = getattr(wf_mod, f"build_{agent.lower()}_graph", None) or getattr(wf_mod, "build_graph")
#         if build_graph_func is None:
#             raise AttributeError(f"CRITICAL: Could not find build function in {workflow_module_name}.py")
#
#         # 重新取角色卡（與上面同值，保持一致）
#         role_card_prompt = get_system_prompt(agent, policy)
#
#         all_tools_for_agent = tools_stage1 + extra_tools
#         #
#         tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in all_tools_for_agent]
#         print(f"[DEBUG] tools registered for {agent}:", tool_names)
#         #
#         executor = create_exec_func("augmented", all_tools_for_agent, system_prompt=role_card_prompt)
#
#         sig = inspect.signature(build_graph_func)
#         params = sig.parameters
#
#         def _noop_validator(s: dict) -> dict:
#             return s
#
#         build_args = {
#             "agent_state_cls": AgentState,
#             "executor": executor,
#             "de_executor": executor,
#             "ds_executor": executor,
#             "tool_map": tool_map,
#             "final_node_func": _noop_validator,
#             "ds_validator_node": _noop_validator,
#             "mode": "augmented",
#         }
#         if agent == "DS":
#             build_args["entry_point"] = "DataScientist"
#         final_args = {p: build_args[p] for p in params if p in build_args}
#         graph = build_graph_func(**final_args)
#         _GRAPH_CACHE[cache_key] = graph
#
#     # ---- 單一來源：在 state 決定 RUN_ID，並同步到環境變數 ----
#     rid = state.get("run_id") or os.getenv("RUN_ID") or f"run_{uuid.uuid4().hex[:8]}"
#     state["run_id"] = rid
#     os.environ["RUN_ID"] = str(rid)
#     print(f"[DEBUG] ensure_run_id -> RUN_ID={rid}")
#
#     if state.get("db_url"):
#         os.environ["DATABASE_URL"] = state["db_url"]
#
#     # === 關鍵：訊息順序要讓「最後一則」是子代理要接的 Human 指令 ===
#     msgs = state.get("messages", []) + intro_msgs
#
#     # 保險：確保最後一則真的是 HumanMessage（有些路徑可能仍以 AIMessage 結尾）
#     if not msgs or not isinstance(msgs[-1], HumanMessage):
#         # 用 intro 裡的最後一句當補充；若沒有，就放一個最小任務提示
#         fallback_text = intro_msgs[-1].content if intro_msgs else "Please proceed with the delegated task."
#         msgs.append(HumanMessage(content=fallback_text))
#
#     sub_state = {
#         "messages": msgs,
#         "metrics": {},
#         "tool_events": [],
#         "hits": [],
#         "blackboard": state.get("blackboard", {}),
#         "policy": policy,
#         "run_id": rid,
#     }
#
#     return graph.invoke(sub_state)

def _invoke_stage1(agent: str, intro_msgs: List[HumanMessage], extra_tools: List, state: Dict[str, Any],
                   success_criteria: Optional[str] = None):
    # 固定 policy 與取得角色卡
    policy = POLICY
    role_card_prompt = get_system_prompt(agent, policy)
    prompt_hash = abs(hash(role_card_prompt)) & 0xFFFF
    cache_key = f"{agent}_augmented_{policy}_{prompt_hash}"

    # 建/取子圖執行器
    if cache_key in _GRAPH_CACHE:
        graph = _GRAPH_CACHE[cache_key]
    else:
        try:
            from common import AgentState  # 你的專案內的 AgentState；如果沒有就 fallback
        except ImportError:
            AgentState = dict

        tools_mod = __import__(f"{agent.lower()}_tools")
        get_tools_func = getattr(tools_mod, f"get_{agent.lower()}_tools")
        tools_stage1, tool_map = get_tools_func("augmented")

        # === 極小補強 (1)：tool_map 先收錄基礎工具，再用 extra_tools 覆蓋 ===
        def _tname(t):
            return getattr(t, "name", getattr(t, "__name__", str(t)))

        for t in tools_stage1:
            nm = _tname(t)
            if nm not in tool_map:
                tool_map[nm] = t
        for t in (extra_tools or []):
            tool_map[_tname(t)] = t  # 覆蓋同名 → 以注入工具為準

        # === 極小補強 (2)：合併工具清單並去重，確保注入工具存在且不被覆蓋 ===
        merged = []
        seen = set()
        for t in (tools_stage1 or []) + (extra_tools or []):
            nm = _tname(t)
            if nm in seen:
                # 以最後看到的版本（通常是 extra_tools）覆蓋：先移除舊的，再附加
                for i in range(len(merged) - 1, -1, -1):
                    if _tname(merged[i]) == nm:
                        merged.pop(i)
                        break
            seen.add(nm)
            merged.append(t)
        all_tools_for_agent = merged

        # Debug：印出實際註冊的工具（含你注入的 request_delegate）
        tool_names = [_tname(t) for t in all_tools_for_agent]
        print(f"[DEBUG] tools registered for {agent}:", tool_names)

        workflow_module_name = "ds_workflow_s2" if agent == "DS" else f"{agent.lower()}_workflow"
        wf_mod = __import__(workflow_module_name)
        create_exec_func = getattr(wf_mod, f"create_{agent.lower()}_executor")
        build_graph_func = getattr(wf_mod, f"build_{agent.lower()}_graph", None) or getattr(wf_mod, "build_graph")
        if build_graph_func is None:
            raise AttributeError(f"CRITICAL: Could not find build function in {workflow_module_name}.py")

        # 重新取角色卡（與上面同值，保持一致）
        role_card_prompt = get_system_prompt(agent, policy)

        executor = create_exec_func("augmented", all_tools_for_agent, system_prompt=role_card_prompt)

        sig = inspect.signature(build_graph_func)
        params = sig.parameters

        def _noop_validator(s: dict) -> dict:
            return s

        build_args = {
            "agent_state_cls": AgentState,
            "executor": executor,
            "de_executor": executor,
            "ds_executor": executor,
            "tool_map": tool_map,               # ★ 保證含有注入工具（如 request_delegate）
            "final_node_func": _noop_validator,
            "ds_validator_node": _noop_validator,
            "mode": "augmented",
        }
        if agent == "DS":
            build_args["entry_point"] = "DataScientist"
        final_args = {p: build_args[p] for p in params if p in build_args}
        graph = build_graph_func(**final_args)
        _GRAPH_CACHE[cache_key] = graph

    # ---- 單一來源：在 state 決定 RUN_ID，並同步到環境變數 ----
    rid = state.get("run_id") or os.getenv("RUN_ID") or f"run_{uuid.uuid4().hex[:8]}"
    state["run_id"] = rid
    os.environ["RUN_ID"] = str(rid)
    print(f"[DEBUG] ensure_run_id -> RUN_ID={rid}")

    if state.get("db_url"):
        os.environ["DATABASE_URL"] = state["db_url"]

    # === Anchor 方案：bb_index + task contract 作為最後一則 HumanMessage，不被壓縮 ===
    from context_assembler import DynamicContextAssembler as _DCA
    _ca = _DCA()
    task_text = intro_msgs[-1].content if intro_msgs else "Please proceed with the delegated task."
    bb_index = _format_bb_index(state.get("blackboard", {}))
    contract = _format_task_contract(task_text, success_criteria)
    anchor_msg = HumanMessage(content=f"{bb_index}\n\n{contract}")
    history_msgs = state.get("messages", [])
    compressed_history = _ca.compress_messages(history_msgs, target_tokens=6000)
    msgs = compressed_history + [anchor_msg]  # anchor 永遠在最後，不被截斷

    sub_state = {
        "messages": msgs,
        "metrics": {},
        "tool_events": [],
        "hits": [],
        "blackboard": state.get("blackboard", {}),
        "policy": policy,
        "run_id": rid,
    }

    return graph.invoke(sub_state)



# def _run_subgraph(agent: str, state: Dict[str, Any], task_text: str, intro_note: str,
#                   topic_id: Optional[str] = None,
#                   owner: Optional[str] = None) -> Dict[str, Any]:
#     # 同步 meta 到環境（保險）
#     os.environ["SEED"] = str(get_seed(state))
#     os.environ["TASK_ID"] = state.get("task_id","")
#     os.environ["PROMPT_CONDITION"] = state.get("prompt_condition","")
#     # 固定亂數源
#     set_global_seeds(get_seed(state))
#
#     injected_tools, p2p_req_box = make_blackboard_tools(state, agent)
#     snapshot = bb_snapshot_text(state, max_items=2)
#     task_with_context = f"{task_text}\n\n{snapshot}"
#     intro_messages = [
#         HumanMessage(content=f"[Instructions]\n{intro_note}"),
#         HumanMessage(content=f"[Your Task]\n{task_with_context}")
#     ]
#     state.setdefault("topic_ctx", {})
#     if topic_id: state["topic_ctx"]["topic_id"] = topic_id
#     if owner:    state["topic_ctx"]["owner"] = owner
#     # out_state = _invoke_stage1(agent, intro_messages, injected_tools, state)
#
#     rl = get_run_logger()
#     task_id = rl.new_task(by="Supervisor", to=agent, instruction=task_text, parent_task_id=None)
#     os.environ["TASK_ID"] = task_id
#
#     try:
#         with rl.agent_node(agent=agent, task_id=task_id):
#             out_state = _invoke_stage1(agent, intro_messages, injected_tools, state)
#         rl.close_task(task_id, status="done")
#     except Exception as e:
#         rl.close_task(task_id, status="failed")
#         rl.error_event(
#             agent=agent,
#             kind="subgraph_error",
#             message=str(e),
#             task_id=task_id,
#             recovered=False,
#             exc=e
#         )
#         raise
#
#     # 回寫全域可觀測性
#     if out_state.get("tool_events"):
#         state.setdefault("tool_events", []).extend(out_state["tool_events"])
#     if out_state.get("metrics"):
#         state.setdefault("metrics", {}).update(out_state.get("metrics", {}))
#
#     # ⚠️ 不再用最後一則 message.content，改用更穩健的摘要器
#     summary = _summarize_out(agent, out_state, max_items=4)
#
#     result = {"status": "ok", "agent": agent, "summary": summary}
#     if p2p_req_box:
#         result["delegate_requests"] = p2p_req_box
#     # 也可以順便把 hits/metrics 帶回，方便上層決策
#     result["hits"] = out_state.get("hits", [])
#     result["metrics"] = out_state.get("metrics", {})
#
#     try:
#         tev = out_state.get("tool_events", [])
#         counts = {}
#         for ev in tev:
#             t = ev.get("tool");
#             counts[t] = counts.get(t, 0) + 1
#         print(f"[{agent}] subgraph summary: tools_used={counts} "
#               f"messages={len(out_state.get('messages', []))} "
#               f"hits={len(out_state.get('hits', [])) if out_state.get('hits') else 0}")
#     except Exception:
#         pass
#
#     return result

# def _run_subgraph(agent: str,
#                   state: Dict[str, Any],
#                   task_text: str,
#                   intro_note: str,
#                   topic_id: Optional[str] = None,
#                   owner: Optional[str] = None,
#                   injected_tools: Optional[List] = None) -> Dict[str, Any]:
#     """
#     跑某個 agent 的子圖。
#     - 會把黑板工具裝上（make_blackboard_tools）
#     - 並把外部注入的工具 injected_tools 一起合併（例如 request_delegate）
#     """
#     # 同步 meta 到環境（保險）
#     os.environ["SEED"] = str(get_seed(state))
#     os.environ["TASK_ID"] = state.get("task_id", "")
#     os.environ["PROMPT_CONDITION"] = state.get("prompt_condition", "")
#
#     # 固定亂數源
#     set_global_seeds(get_seed(state))
#
#     # 先取黑板工具（保持原有行為）；同時接住它的 p2p 信箱（若有）
#     bb_tools, bb_p2p_box = make_blackboard_tools(state, agent)
#
#     # 合併工具：黑板工具 + 上層注入工具（例如：request_delegate）
#     tools_for_stage = (bb_tools or []) + (injected_tools or [])
#
#     # 任務上下文
#     snapshot = bb_snapshot_text(state, max_items=2)
#     task_with_context = f"{task_text}\n\n{snapshot}"
#     intro_messages = [
#         HumanMessage(content=f"[Instructions]\n{intro_note}"),
#         HumanMessage(content=f"[Your Task]\n{task_with_context}")
#     ]
#
#     # 暫存 topic/owner
#     state.setdefault("topic_ctx", {})
#     if topic_id:
#         state["topic_ctx"]["topic_id"] = topic_id
#     if owner:
#         state["topic_ctx"]["owner"] = owner
#
#     # 建立並進入 RunLogger 任務節點
#     rl = get_run_logger()
#     task_id = rl.new_task(by="Supervisor", to=agent, instruction=task_text, parent_task_id=None)
#     os.environ["TASK_ID"] = task_id
#
#     try:
#         with rl.agent_node(agent=agent, task_id=task_id):
#             # ★ 關鍵：把合併後的 tools_for_stage 傳入
#             out_state = _invoke_stage1(agent, intro_messages, tools_for_stage, state)
#         rl.close_task(task_id, status="done")
#     except Exception as e:
#         rl.close_task(task_id, status="failed")
#         rl.error_event(
#             agent=agent,
#             kind="subgraph_error",
#             message=str(e),
#             task_id=task_id,
#             recovered=False,
#             exc=e
#         )
#         raise
#
#     # 回寫全域可觀測性
#     if out_state.get("tool_events"):
#         state.setdefault("tool_events", []).extend(out_state["tool_events"])
#     if out_state.get("metrics"):
#         state.setdefault("metrics", {}).update(out_state.get("metrics", {}))
#
#     # 產出摘要（比直接拿最後一則訊息穩）
#     summary = _summarize_out(agent, out_state, max_items=4)
#
#     result = {"status": "ok", "agent": agent, "summary": summary}
#
#     # 若黑板工具本身也提供了 P2P 信箱，幫你帶回（上層可以選擇是否轉成事件）
#     if bb_p2p_box:
#         result["delegate_requests"] = bb_p2p_box
#
#     # 也把 hits/metrics 往上帶，方便上層決策
#     result["hits"] = out_state.get("hits", [])
#     result["metrics"] = out_state.get("metrics", {})
#
#     # 簡易列印摘要
#     try:
#         tev = out_state.get("tool_events", [])
#         counts = {}
#         for ev in tev:
#             t = ev.get("tool")
#             counts[t] = counts.get(t, 0) + 1
#         print(f"[{agent}] subgraph summary: tools_used={counts} "
#               f"messages={len(out_state.get('messages', []))} "
#               f"hits={len(out_state.get('hits', [])) if out_state.get('hits') else 0}")
#     except Exception:
#         pass
#
#     return result

# ---------- delegate_tools.py : Paste-OVER (2/2) ----------

def _run_subgraph(agent: str,
                  state: Dict[str, Any],
                  task_text: str,
                  intro_note: str,
                  *,
                  topic_id: Optional[str] = None,
                  owner: Optional[str] = None,
                  injected_tools: Optional[List[Any]] = None,
                  success_criteria: Optional[str] = None) -> Dict[str, Any]:
    """統一的子圖執行器：把外部注入的工具清單（黑板+P2P）傳進 Stage1"""

    # 同步 meta → env；固定亂數
    os.environ["SEED"] = str(get_seed(state))
    os.environ["TASK_ID"] = state.get("task_id", "")
    os.environ["PROMPT_CONDITION"] = state.get("prompt_condition", "")
    set_global_seeds(get_seed(state))

    snapshot = bb_snapshot_text(state, max_items=2)
    task_with_context = f"{task_text}\n\n{snapshot}"
    intro_messages = [
        HumanMessage(content=f"[Instructions]\n{intro_note}"),
        HumanMessage(content=f"[Your Task]\n{task_with_context}")
    ]

    # 把 topic/owner 放入 state['topic_ctx']
    state.setdefault("topic_ctx", {})
    if topic_id:
        state["topic_ctx"]["topic_id"] = topic_id
    if owner:
        state["topic_ctx"]["owner"] = owner

    rl = get_run_logger()
    task_id = rl.new_task(by="Supervisor", to=agent, instruction=task_text, parent_task_id=None)
    os.environ["TASK_ID"] = task_id

    try:
        with rl.agent_node(agent=agent, task_id=task_id):
            out_state = _invoke_stage1(agent, intro_messages, injected_tools or [], state,
                                       success_criteria=success_criteria)
        rl.close_task(task_id, status="done")
    except Exception as e:
        rl.close_task(task_id, status="failed")
        rl.error_event(
            agent=agent,
            kind="subgraph_error",
            message=str(e),
            task_id=task_id,
            recovered=False,
            exc=e
        )
        raise

    # 回寫可觀測性/統計
    if out_state.get("tool_events"):
        state.setdefault("tool_events", []).extend(out_state["tool_events"])
    if out_state.get("metrics"):
        _merge_metrics(state.setdefault("metrics", {}), out_state.get("metrics", {}))

    # console 摘要（不影響流程）
    try:
        tev = out_state.get("tool_events", []) or []
        counts = {}
        for ev in tev:
            t = ev.get("tool")
            counts[t] = counts.get(t, 0) + 1
        print(f"[{agent}] subgraph summary: tools_used={counts} "
              f"messages={len(out_state.get('messages', []))} "
              f"hits={len(out_state.get('hits', [])) if out_state.get('hits') else 0}")
    except Exception:
        pass

    return out_state



def _summarize_out(agent: str, out_state: Dict[str, Any], max_items: int = 4) -> str:
    """
    更穩健的摘要抽取順序：
      0) Pydantic primary path：從最後一條 AIMessage 嘗試解析 MEReport/DSReport/DEReport
      1) 優先抓 synth 工具（synthesize_and_cite）的 cited_answer
      2) 再抓本輪寫進黑板的事實（bb_write_fact）做成要點
      3) 最後退：從已讀 chunk 提取1-2條線索（doc_id p.#）
      4) 都沒有 → 給非空的 fallback 字串
    """
    # (0) Pydantic primary path
    try:
        from structured_outputs import MEReport, DSReport, DEReport
        import re as _re
        _agent_upper = agent.upper()
        _report_cls = {"ME": MEReport, "DS": DSReport, "DE": DEReport}.get(_agent_upper)
        if _report_cls:
            for msg in reversed(out_state.get("messages", [])):
                raw = getattr(msg, "content", "") or ""
                if not raw:
                    continue
                _json_str = re.sub(r"```(?:json)?", "", raw).strip()
                _m = re.search(r"\{.*\}", _json_str, re.DOTALL)
                if _m:
                    try:
                        report = _report_cls.model_validate_json(_m.group(0))
                        summary_field = getattr(report, "answer", None) or getattr(report, "summary", None) or ""
                        if len(summary_field) >= 5:
                            return summary_field.strip()
                    except Exception:
                        pass
    except Exception:
        pass

    lines: List[str] = []

    # (1) messages 裡找 synth 工具輸出
    try:
        for msg in reversed(out_state.get("messages", [])):
            if getattr(msg, "name", "") == "synthesize_and_cite":
                try:
                    payload = json.loads(getattr(msg, "content", "") or "{}")
                    ans = payload.get("cited_answer") or payload.get("envelope", {}).get("answer")
                    if isinstance(ans, str) and ans.strip():
                        lines.append(ans.strip())
                        break
                except Exception:
                    pass
    except Exception:
        pass

    # (1b) 抓不到就從 tool_events 的 synth output_head 找
    if not lines:
        for ev in reversed(out_state.get("tool_events", [])):
            if ev.get("tool") == "synthesize_and_cite":
                try:
                    payload = json.loads(ev.get("output_head") or "{}")
                    ans = payload.get("cited_answer") or payload.get("envelope", {}).get("answer")
                    if isinstance(ans, str) and ans.strip():
                        lines.append(ans.strip())
                        break
                except Exception:
                    pass

    # (2) 沒有 synth，就彙整 bb_write_fact 的要點
    if not lines:
        facts = []
        for ev in out_state.get("tool_events", []):
            if ev.get("tool") == "bb_write_fact":
                try:
                    j = json.loads(ev.get("output_head") or "{}")
                    fact = (j.get("fact") or {}).get("text")
                    src  = (j.get("fact") or {}).get("source")
                    if fact:
                        facts.append(f"- {fact}" + (f"  ({src})" if src else ""))
                except Exception:
                    pass
        if facts:
            lines.extend(facts[-max_items:])

    # (3) 最後退：從 hits 的 chunk 列出已查到的來源線索
    if not lines:
        hints = []
        for h in (out_state.get("hits") or [])[:max_items]:
            ch = (h.get("chunk") or {})
            if ch.get("doc_id"):
                hints.append(f"- seen: {ch.get('doc_id')} p.{int(ch.get('page', 0))}")
        if hints:
            lines.append("Evidence scanned:\n" + "\n".join(hints))

    # (4) 補上 1–2 行 citation（若有）
    if lines:
        try:
            from bb_tools import _load as _bb_load
            reg = _bb_load(os.getenv("RUN_ID"))
            cits = reg.get("citations", [])[-2:]
            if cits:
                src_line = "Sources: " + "; ".join(
                    f"{c.get('doc_id')} p.{c.get('page')}" for c in cits
                )
                lines.append(src_line)
        except Exception:
            pass

    summary = "\n".join(lines).strip()

    # (4) DE: extract SQL query or deliver_dataframe result from ToolMessages
    if not summary:
        from langchain_core.messages import ToolMessage as _TM
        _data_tools = {"sql_db_query", "deliver_dataframe"}
        for msg in reversed(out_state.get("messages", [])):
            if isinstance(msg, _TM) and getattr(msg, "name", "") in _data_tools:
                try:
                    d = json.loads(msg.content)
                    if d.get("status") == "ok":
                        rows = d.get("rows", [])
                        rc = d.get("rowcount", 0)
                        cols = d.get("columns", [])
                        summary = f"SQL result: rowcount={rc}, columns={cols}"
                        if rows and rc <= 20:
                            summary += f", rows={json.dumps(rows, ensure_ascii=False)}"
                        elif rows:
                            summary += f", first_row={json.dumps(rows[0], ensure_ascii=False)}"
                except Exception:
                    summary = (msg.content or "")[:500]
                if summary:
                    break

    # (5) Final fallback: last AIMessage.content (ME's synthesized thought)
    if not summary:
        for msg in reversed(out_state.get("messages", [])):
            if isinstance(msg, AIMessage):
                c = getattr(msg, "content", "") or ""
                if isinstance(c, list):
                    c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
                c = c.strip()
                # Skip empty, JSON-only, or tool-routing messages
                if len(c) >= 20 and not c.startswith("{") and "tool_call" not in c.lower():
                    summary = c[:1500]
                    break

    return summary or f"{agent} finished with no extractable summary."


# def delegate_to_me(question: str, state: Dict[str, Any],
#                    topic_id: Optional[str] = None,
#                    owner: Optional[str] = None) -> Dict[str, Any]:
#     """ME 子圖：現在會帶著 topic/owner 跑，讓黑板與事件有正確鏈路"""
#     intro = "You are the Machine Expert. Use your RAG and blackboard tools to answer the question."
#     # 將 topic/owner 暫存進 state['topic_ctx']，離開時還原
#     with _TopicCtx(state, topic_id, owner):
#         try:
#             import me_tools
#             me_tools.init_me_index_from_dir(state.get("pdf_dir", "./TEP_docs"))
#
#         except Exception as e:
#             return {"agent": "ME", "summary": f"Init RAG failed: {e}", "status": "error",
#                     "topic_id": _topic_from(state, topic_id), "owner": _owner_from(state, owner)}
#         # 跑子圖
#         out_state = _run_subgraph("ME", state, question, intro,
#                                   topic_id=_topic_from(state, topic_id),
#                                   owner=_owner_from(state, owner))
#         # 避免空回覆
#         summary = _summarize_out("ME", out_state, max_items=4)
#         try:
#             for m in reversed(out_state.get("messages", [])):
#                 if isinstance(m, AIMessage) and (m.content or "").strip():
#                     summary = (m.content or "").strip()
#                     break
#         except Exception:
#             pass
#         return {
#             "agent": "ME",
#             "summary": summary,
#             "tool_events": out_state.get("tool_events", []),
#             "hits": out_state.get("hits", []),
#             "metrics": out_state.get("metrics", {}),
#             "status": "ok",
#             "topic_id": _topic_from(state, topic_id),
#             "owner": _owner_from(state, owner),
#         }
#
# def delegate_to_de(task: str, state: Dict[str, Any],
#                    topic_id: Optional[str] = None,
#                    owner: Optional[str] = None) -> Dict[str, Any]:
#     """DE 子圖"""
#     intro = "You are the Data Engineer. Use your SQL and blackboard tools to fulfill the data request."
#     with _TopicCtx(state, topic_id, owner):
#         return _run_subgraph("DE", state, task, intro,
#                              topic_id=_topic_from(state, topic_id),
#                              owner=_owner_from(state, owner))
#
# def delegate_to_ds(task: str, state: Dict[str, Any],
#                    topic_id: Optional[str] = None,
#                    owner: Optional[str] = None) -> Dict[str, Any]:
#     """DS 子圖"""
#     intro = "You are the Data Scientist. Use your Python and blackboard tools to analyze data or fulfill the request."
#     with _TopicCtx(state, topic_id, owner):
#         return _run_subgraph("DS", state, task, intro,
#                              topic_id=_topic_from(state, topic_id),
#                              owner=_owner_from(state, owner))

# # ---------- delegate_tools.py : Paste-OVER (1/2) ----------
#
# def delegate_to_me(question: str, state: Dict[str, Any],
#                    topic_id: Optional[str] = None,
#                    owner: Optional[str] = None) -> Dict[str, Any]:
#     """ME 子圖：帶 topic/owner 跑；注入黑板+P2P 工具；回合後把 P2P 請求落成正式事件"""
#     intro = "You are the Machine Expert. Use your RAG and blackboard tools to answer the question."
#
#     # 只用黑板工廠（內含 request_delegate + p2p_req_box）
#     bb_tools_list, p2p_box = make_blackboard_tools(state, agent_name="ME")
#
#     with _TopicCtx(state, topic_id, owner):
#         # 初始化 RAG
#         try:
#             import me_tools
#             me_tools.init_me_index_from_dir(state.get("pdf_dir", "./TEP_docs"))
#         except Exception as e:
#             return {
#                 "agent": "ME", "status": "error",
#                 "summary": f"Init RAG failed: {e}",
#                 "topic_id": _topic_from(state, topic_id),
#                 "owner": _owner_from(state, owner)
#             }
#
#         # 子圖執行（把黑板+P2P 工具注入）
#         out_state = _run_subgraph(
#             agent="ME", state=state, task_text=question, intro_note=intro,
#             topic_id=_topic_from(state, topic_id),
#             owner=_owner_from(state, owner),
#             injected_tools=bb_tools_list,
#         )
#
#         # 把本回合提出的 P2P 請求記成正式事件（純記錄，不改動 Router 流程）
#         try:
#             for req in list(p2p_box or []):
#                 emit_delegate_event(
#                     caller_agent="ME",
#                     target_agent=req.get("to", ""),
#                     topic_id=_topic_from(state, topic_id),
#                     reason=req.get("task", ""),
#                     turn_index=state.get("turn_counter"),
#                     state=state
#                 )
#         except Exception:
#             pass
#
#         # 兜底摘要
#         summary = _summarize_out("ME", out_state, max_items=4)
#         try:
#             for m in reversed(out_state.get("messages", [])):
#                 if isinstance(m, AIMessage) and (m.content or "").strip():
#                     summary = (m.content or "").strip()
#                     break
#         except Exception:
#             pass
#
#         return {
#             "agent": "ME", "status": "ok",
#             "summary": summary,
#             "tool_events": out_state.get("tool_events", []),
#             "hits": out_state.get("hits", []),
#             "metrics": out_state.get("metrics", {}),
#             "topic_id": _topic_from(state, topic_id),
#             "owner": _owner_from(state, owner),
#             # 關鍵：把 P2P 請求帶回 Router，才能啟動 Router 的 P2P 迴圈
#             "delegate_requests": list(p2p_box or []),
#         }
#
#
# def delegate_to_de(task: str, state: Dict[str, Any],
#                    topic_id: Optional[str] = None,
#                    owner: Optional[str] = None) -> Dict[str, Any]:
#     """DE 子圖：同 ME，回傳時帶 delegate_requests 給 Router"""
#     intro = "You are the Data Engineer. Use your SQL and blackboard tools to fulfill the data request."
#
#
#     bb_tools_list, p2p_box = make_blackboard_tools(state, agent_name="DE")
#
#     with _TopicCtx(state, topic_id, owner):
#         out_state = _run_subgraph(
#             agent="DE", state=state, task_text=task, intro_note=intro,
#             topic_id=_topic_from(state, topic_id),
#             owner=_owner_from(state, owner),
#             injected_tools=bb_tools_list,
#         )
#
#         # 記成正式事件（純記錄）
#         try:
#             for req in list(p2p_box or []):
#                 emit_delegate_event(
#                     caller_agent="DE",
#                     target_agent=req.get("to", ""),
#                     topic_id=_topic_from(state, topic_id),
#                     reason=req.get("task", ""),
#                     turn_index=state.get("turn_counter"),
#                     state=state
#                 )
#         except Exception:
#             pass
#
#         # 兜底摘要
#         summary = _summarize_out("DE", out_state, max_items=4)
#
#         return {
#             "agent": "DE", "status": "ok",
#             "summary": summary,
#             "tool_events": out_state.get("tool_events", []),
#             "hits": out_state.get("hits", []),
#             "metrics": out_state.get("metrics", {}),
#             "topic_id": _topic_from(state, topic_id),
#             "owner": _owner_from(state, owner),
#             "delegate_requests": list(p2p_box or []),
#         }
#
#
# def delegate_to_ds(task: str, state: Dict[str, Any],
#                    topic_id: Optional[str] = None,
#                    owner: Optional[str] = None) -> Dict[str, Any]:
#     """DS 子圖：同 DE，回傳時帶 delegate_requests 給 Router"""
#     intro = "You are the Data Scientist. Use your Python and blackboard tools to analyze data or fulfill the request."
#
#     bb_tools_list, p2p_box = make_blackboard_tools(state, agent_name="DS")
#
#     with _TopicCtx(state, topic_id, owner):
#         out_state = _run_subgraph(
#             agent="DS", state=state, task_text=task, intro_note=intro,
#             topic_id=_topic_from(state, topic_id),
#             owner=_owner_from(state, owner),
#             injected_tools=bb_tools_list,
#         )
#
#         # 記成正式事件（純記錄）
#         try:
#             for req in list(p2p_box or []):
#                 emit_delegate_event(
#                     caller_agent="DS",
#                     target_agent=req.get("to", ""),
#                     topic_id=_topic_from(state, topic_id),
#                     reason=req.get("task", ""),
#                     turn_index=state.get("turn_counter"),
#                     state=state
#                 )
#         except Exception:
#             pass
#
#         summary = _summarize_out("DS", out_state, max_items=4)
#
#         return {
#             "agent": "DS", "status": "ok",
#             "summary": summary,
#             "tool_events": out_state.get("tool_events", []),
#             "hits": out_state.get("hits", []),
#             "metrics": out_state.get("metrics", {}),
#             "topic_id": _topic_from(state, topic_id),
#             "owner": _owner_from(state, owner),
#             "delegate_requests": list(p2p_box or []),
#         }

# --- paste to: delegate_tools.py (replace these three functions) ---
def delegate_to_me(question: str, state: Dict[str, Any],
                   topic_id: Optional[str] = None,
                   owner: Optional[str] = None,
                   success_criteria: Optional[str] = None) -> Dict[str, Any]:
    """ME 子圖：帶 topic/owner 跑，注入 P2P 工具；回合結束後把委派請求記成事件"""
    intro = "You are the Machine Expert. Use your RAG and blackboard tools to answer the question."
    p2p_tools, p2p_box = make_blackboard_tools(state, agent_name="ME")
    with _TopicCtx(state, topic_id, owner):
        rag_note = ""
        try:
            import me_tools
            me_tools.init_me_index_from_dir(state.get("pdf_dir", "./TEP_docs"))
        except Exception as e:
            rag_note = (
                f"\n\n[System] RAG document index unavailable ({type(e).__name__})."
                " Use kg_query_fault(N) as primary knowledge source."
                " Blackboard and KG tools remain available."
            )
        task_with_rag_status = question + rag_note
        out_state = _run_subgraph("ME", state, task_with_rag_status, intro,
                                  topic_id=_topic_from(state, topic_id),
                                  owner=_owner_from(state, owner),
                                  injected_tools=p2p_tools,
                                  success_criteria=success_criteria)
        _extract_and_write_me_fault_facts(out_state)  # Plan D: write structured facts to BB
        # 將本回合提出的 P2P 請求一併回傳
        result = {
            "agent": "ME",
            "summary": _summarize_out("ME", out_state, max_items=4),
            "tool_events": out_state.get("tool_events", []),
            "hits": out_state.get("hits", []),
            "metrics": out_state.get("metrics", {}),
            "status": "ok",
            "topic_id": _topic_from(state, topic_id),
            "owner": _owner_from(state, owner),
        }
        if p2p_box:
            result["delegate_requests"] = list(p2p_box)
        return result


def delegate_to_de(task: str, state: Dict[str, Any],
                   topic_id: Optional[str] = None,
                   owner: Optional[str] = None,
                   success_criteria: Optional[str] = None) -> Dict[str, Any]:
    """DE 子圖：注入 P2P 工具；回合結束把委派請求回傳"""
    intro = "You are the Data Engineer. Use your SQL and blackboard tools to fulfill the data request."
    p2p_tools, p2p_box = make_blackboard_tools(state, agent_name="DE")
    with _TopicCtx(state, topic_id, owner):
        me_facts = _read_me_fault_facts()  # Plan B: inject ME fault context
        if me_facts:
            task = f"[Context from ME]\n{me_facts}\n\n{task}"
        out_state = _run_subgraph("DE", state, task, intro,
                                  topic_id=_topic_from(state, topic_id),
                                  owner=_owner_from(state, owner),
                                  injected_tools=p2p_tools,
                                  success_criteria=success_criteria)
        result = {
            "status": "ok",
            "agent": "DE",
            "summary": _summarize_out("DE", out_state, max_items=4),
            "tool_events": out_state.get("tool_events", []),
            "hits": out_state.get("hits", []),
            "metrics": out_state.get("metrics", {}),
            "topic_id": _topic_from(state, topic_id),
            "owner": _owner_from(state, owner),
        }
        if p2p_box:
            result["delegate_requests"] = list(p2p_box)
        return result


def delegate_to_ds(task: str, state: Dict[str, Any],
                   topic_id: Optional[str] = None,
                   owner: Optional[str] = None,
                   success_criteria: Optional[str] = None) -> Dict[str, Any]:
    """DS 子圖：注入 P2P 工具；回合結束把委派請求回傳"""
    intro = "You are the Data Scientist. Use your Python and blackboard tools to analyze data or fulfill the request."
    p2p_tools, p2p_box = make_blackboard_tools(state, agent_name="DS")
    with _TopicCtx(state, topic_id, owner):
        out_state = _run_subgraph("DS", state, task, intro,
                                  topic_id=_topic_from(state, topic_id),
                                  owner=_owner_from(state, owner),
                                  injected_tools=p2p_tools,
                                  success_criteria=success_criteria)
        result = {
            "status": "ok",
            "agent": "DS",
            "summary": _summarize_out("DS", out_state, max_items=4),
            "tool_events": out_state.get("tool_events", []),
            "hits": out_state.get("hits", []),
            "metrics": out_state.get("metrics", {}),
            "topic_id": _topic_from(state, topic_id),
            "owner": _owner_from(state, owner),
        }
        if p2p_box:
            result["delegate_requests"] = list(p2p_box)
        return result


def continue_agent(agent_name: str, state: Dict[str, Any], feedback: str) -> Dict[str, Any]:
    intro_note = f"[Feedback from Colleagues]\n{feedback}\n\n[Your Task]\nBased on this new information, continue your work."
    return _run_subgraph(agent_name.upper(), state, "Continue your task based on the feedback.", intro_note)
