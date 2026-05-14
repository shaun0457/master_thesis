# router.py (最终融合版 - 带安全护栏)
import json, os, uuid, hashlib, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional, List, Set
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from delegate_tools import delegate_to_me, delegate_to_de, delegate_to_ds, continue_agent
try:
    # 盡量沿用你原本的（若存在）；沒有就設為 None
    from common import ensure_topic_in_args as _ensure_topic_in_args_orig  # type: ignore
except Exception:
    _ensure_topic_in_args_orig = None
import time
from metrics import note_tool_event
from run_logger import  note_tool_call
try:
    import common as _COMMON  # expects (state)
except Exception:
    _ensure_run_id_state = None
from run_logger import emit_event, _now_ms, new_uuid
import traceback


# _MAX_P2P_HOPS = 8
MAX_SUMMARY_CHARS = 1000  # 可以适当放宽，因为现在内容更简洁
_MAX_P2P_HOPS= int(os.getenv("MAX_P2P_HOPS_PER_TURN", "8"))
_MAX_OPEN_REQS = int(os.getenv("MAX_OPEN_REQS_PER_TURN", "8"))
MAX_GLOBAL_TOOL_CALLS = int(os.getenv("MAX_GLOBAL_TOOL_CALLS", "25"))

# Plan A: lock guards global_tool_calls counter against parallel increment race
_metrics_lock = threading.Lock()

# Parallel delegation is disabled until blackboard/state mutations are fully thread-safe.
_PARALLEL_CAPABLE = set()

def _norm_agent_name(s: str) -> str:
    return (s or "").strip().upper()

def _dedup_key(req: dict) -> str:
    """用 req_id 去重；若沒有 req_id，用 (to + contract + task_sig) 產生穩定 key。"""
    rid = (req or {}).get("req_id")
    if rid:
        return f"RID:{rid}"
    to = _norm_agent_name((req or {}).get("to"))
    contract = json.dumps((req or {}).get("contract") or {}, sort_keys=True, ensure_ascii=False)
    task_sig = ((req or {}).get("task") or (req or {}).get("question") or "")[:80]
    h = hashlib.md5((to + "|" + contract + "|" + task_sig).encode("utf-8")).hexdigest()[:8]
    return f"SIG:{to}:{h}"

def _json_safe(obj):
    """把 LangChain 的 Message 等不可序列化物件轉成可 JSON 的基礎型別。"""
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    # LangChain messages → 縮成扁平 dict
    if isinstance(obj, (HumanMessage, AIMessage, SystemMessage, ToolMessage)):
        base = {"type": obj.__class__.__name__, "content": getattr(obj, "content", None)}
        if hasattr(obj, "name"):
            base["name"] = getattr(obj, "name", None)
        return base
    # 其他一律轉字串
    return str(obj)

def _safe_meta_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """帶 run 級 meta（供 ETL 用）。"""
    return {
        "run_id": state.get("run_id") or os.environ.get("RUN_ID", ""),
        "task_id": state.get("task_id") or os.environ.get("TASK_ID", ""),
        "seed": state.get("seed") or os.environ.get("SEED", ""),
        "prompt_condition": state.get("prompt_condition") or os.environ.get("PROMPT_CONDITION", ""),
    }

def _derive_topic_owner_from_state(_state: Dict[str, Any], target_agent: str) -> Dict[str, str]:
    tc = (_state or {}).get("topic_ctx") or {}
    topic_id = tc.get("topic_id") or _state.get("topic_id")
    if not topic_id:
        topic_id = f"topic_{uuid.uuid4().hex[:8]}"
    owner = tc.get("owner") or _state.get("owner") or target_agent
    return {"topic_id": topic_id, "owner": owner}


# ========= helpers =========
def now_ms() -> int:
    return int(time.time() * 1000)

def _root() -> str:
    # 可用環境變數覆寫；預設 /mnt/data/runs
    root = os.environ.get("RUNS_DIR", "/mnt/data/runs")
    os.makedirs(root, exist_ok=True)
    return root

def _resolve_run_id(state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> str:
    if run_id:
        return str(run_id)
    if state:
        for k in ("RUN_ID","run_id","id"):
            if state.get(k):
                return str(state[k])
        if _ensure_run_id_state:
            try:
                rid = _ensure_run_id_state(state)
                if rid: return str(rid)
            except Exception:
                pass
    return os.environ.get("RUN_ID", "unknown_run")

def _run_dir(state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> str:
    rid = _resolve_run_id(state, run_id)
    d = os.path.join(_root(), rid)
    os.makedirs(d, exist_ok=True)
    return d

def _path_events(state=None, run_id=None) -> str:
    return os.path.join(_run_dir(state, run_id), "events.jsonl")

def _path_runmeta(state=None, run_id=None) -> str:
    return os.path.join(_run_dir(state, run_id), "run_meta.json")

def _path_outcome(state=None, run_id=None) -> str:
    return os.path.join(_run_dir(state, run_id), "outcome.json")

def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _consume_p2p_requests(res: Dict[str, Any], state: Dict[str, Any]) -> None:
    """
    讀子圖回傳的 res['delegate_requests']，逐一轉為正式 delegate_to_* 呼叫。
    不回傳資料，也不改你的主流程。
    """
    try:
        reqs: List[Dict[str, Any]] = (res or {}).get("delegate_requests") or []
        if not reqs:
            return

        caller = (res or {}).get("agent") or state.get("current_agent") or "Supervisor"
        for r in reqs:
            to = (r.get("to") or "").strip().upper()
            task = (r.get("task") or "").strip()
            if to not in {"ME", "DE", "DS"} or not task:
                continue

            # 1) 組目標工具名與基本參數
            sub_name = {"ME": "delegate_to_me", "DE": "delegate_to_de", "DS": "delegate_to_ds"}[to]
            base_args = {"question": task} if to == "ME" else {"task": task}

            # 2) 確保 topic/owner（也會回寫 state.topic_ctx）
            try:
                base_args = ensure_topic_in_args(base_args, target_agent=to, state=state)
            except TypeError:
                # 相容舊版 ensure_topic_in_args(state 參數不存在) 的寫法
                base_args = ensure_topic_in_args(base_args, target_agent=to)

            # 3) 真的執行子委派（先過節流計數，再執行）
            with _metrics_lock:
                current = state.get("metrics", {}).get("global_tool_calls", 0)
                if current >= MAX_GLOBAL_TOOL_CALLS:
                    break
                state.setdefault("metrics", {})["global_tool_calls"] = current + 1
            _ = _exec_one_tool(sub_name, base_args, state)

            # 4) 記一條 delegate 邊（誰→誰）
            try:
                emit_delegate_event(
                    caller_agent=caller,
                    target_agent=to,
                    topic_id=base_args.get("topic_id", ""),
                    reason=task,
                    turn_index=state.get("turn_counter"),
                    state=state,
                )
            except Exception:
                traceback.print_exc()

    except Exception:
        traceback.print_exc()

# ========= Run 級 =========
def emit_run_meta(state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None, **meta) -> None:
    """一次性寫入/覆寫 run metadata"""
    path = _path_runmeta(state, run_id)
    cur = {}
    if os.path.exists(path):
        try:
            cur = json.load(open(path, "r", encoding="utf-8"))
        except Exception:
            cur = {}
    cur.update(meta)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)

def begin_run(state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None, **meta) -> None:
    meta.setdefault("start_time_ms", now_ms())
    emit_run_meta(state, run_id, **meta)

def end_run(state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> None:
    emit_run_meta(state, run_id, end_time_ms=now_ms())

# ========= Event 級 =========
def emit_event(e: Dict[str, Any], *, state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> None:
    """每一個行為一列事件：delegate/message/tool_call/bb_write/bb_read/plan_* 等"""
    rid = _resolve_run_id(state, run_id)
    e = dict(e or {})
    e.setdefault("run_id", rid)
    e.setdefault("event_id", new_uuid())
    e.setdefault("timestamp", now_ms())
    e.setdefault("turn_index", e.get("turn_index", None))
    e.setdefault("channel", e.get("channel", "team"))
    assert "event_type" in e and "agent" in e, "event_type/agent 必填"
    _append_jsonl(_path_events(state, run_id), e)

def log_message(*, agent: str, content_text: str, topic_id: Optional[str] = None,
                addressed_to: str = "", channel: str = "team",
                turn_index: Optional[int] = None,
                state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> None:
    emit_event({
        "event_type": "message",
        "agent": agent,
        "addressed_to": addressed_to or "",
        "topic_id": topic_id or "",
        "content_text": (content_text or "")[:800],
        "turn_index": turn_index,
        "channel": channel,
        "run_id": state.get("run_id"),
        "task_id": state.get("task_id"),
        "seed": state.get("seed")
    }, state=state, run_id=run_id)

def note_tool_call(*, agent: str, tool_name: str, ok: Optional[bool]=None,
                   latency_ms: Optional[int]=None, args_head: Optional[str]=None,
                   addressed_to: str = "", topic_id: str = "",
                   state: Optional[Dict[str, Any]] = None,
                   turn_index: Optional[int] = None) -> None:
    emit_event({
        "event_type": f"tool_call:{tool_name}",
        "agent": agent, "addressed_to": addressed_to, "topic_id": topic_id,
        "ok": ok, "latency_ms": latency_ms, "args_head": (args_head or "")[:400],
        "turn_index": turn_index,
        "run_id": state.get("run_id"),
        "task_id": state.get("task_id"),
        "seed": state.get("seed")
    }, state=state)

# ========= Blackboard 讀寫 =========
def emit_bb_write(*, agent: str, topic_id: str, section: str, artifact_id: str,
                  uri: str = "", intended_owner: str = "",
                  turn_index: Optional[int] = None,
                  state: Optional[Dict[str, Any]] = None) -> None:
    emit_event({
        "event_type": "bb_write",
        "agent": agent, "addressed_to": "",
        "topic_id": topic_id, "bb_section": section,
        "bb_write_id": artifact_id, "artifact_uri": uri,
        "intended_owner": intended_owner, "turn_index": turn_index,
        "run_id": state.get("run_id"),
        "task_id": state.get("task_id"),
        "seed": state.get("seed")
    }, state=state)

def emit_bb_read(*, agent: str, topic_id: str, section: str,
                 fact_ids_served: List[str],
                 turn_index: Optional[int] = None,
                 state: Optional[Dict[str, Any]] = None) -> None:
    # 多個 id 可各寫一列（或合併一列帶清單，ETL 時展開）
    if not fact_ids_served:
        fact_ids_served = []
    for fx in fact_ids_served:
        emit_event({
            "event_type": "bb_read",
            "agent": agent, "addressed_to": "",
            "topic_id": topic_id, "bb_section": section,
            "bb_read_of": fx, "turn_index": turn_index,
        "run_id": state.get("run_id"),
        "task_id": state.get("task_id"),
        "seed": state.get("seed")
        }, state=state)

# ========= Compliance / Outcome =========
def emit_compliance(*, state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None, **kv) -> None:
    emit_event({
        "event_type": "compliance",
        "agent": "System", "addressed_to": "",
        **kv,
        "run_id": state.get("run_id"),
        "task_id": state.get("task_id"),
        "seed": state.get("seed")
    }, state=state, run_id=run_id)

def emit_outcome(*, state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None,
                 success_score: float, notes: str = "",
                 turns: Optional[int] = None, messages: Optional[int] = None,
                 tool_calls: Optional[int] = None) -> None:
    # 寫檔（覆寫）
    out = {
        "run_id": _resolve_run_id(state, run_id),
        "success_score": success_score,
        "notes": notes,
        "turns": turns, "messages": messages, "tool_calls": tool_calls,
        "written_at_ms": now_ms()
    }
    with open(_path_outcome(state, run_id), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 也落一列事件
    emit_event({
        "event_type": "outcome",
        "agent": "System", "addressed_to": "",
        **out,
        "run_id": state.get("run_id"),
        "task_id": state.get("task_id"),
        "seed": state.get("seed")
    }, state=state, run_id=run_id)

def _trim(text: Any, max_len: int) -> str:
    if not isinstance(text, str): return str(text)
    return text if len(text) <= max_len else text[:max_len] + " ...[truncated]"

def _short_uuid() -> str:
    import uuid as _u
    return _u.uuid4().hex[:8]


def emit_delegate_event(*, caller_agent: str, target_agent: str, topic_id: str,
                        reason: str, turn_index: int, state: Dict[str, Any]) -> None:
    """
    記一筆 delegate 事件（誰→誰、哪個 topic、哪一輪），並附上 run 級 meta（run_id/task_id/seed/prompt_condition）。
    """
    payload = {
        "event_type": "delegate",
        "agent": caller_agent or "Supervisor",
        "addressed_to": target_agent,
        "topic_id": topic_id,
        "turn_index": int(turn_index or 0),
        "content_head": (reason or "")[:200],
        "meta": {
            "run_id": state.get("run_id") or os.environ.get("RUN_ID", ""),
            "task_id": state.get("task_id") or os.environ.get("TASK_ID", ""),
            "seed": state.get("seed") or os.environ.get("SEED", ""),
            "prompt_condition": state.get("prompt_condition") or os.environ.get("PROMPT_CONDITION", ""),
        },
    }
    try:
        emit_event(payload, state=state)
    except Exception:
        pass

def ensure_topic_in_args(args: Dict[str, Any], target_agent: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    保險包裝：永遠可收 (args, target_agent, state)。
    - 若 state 存在，從 state/topic_ctx 推回 topic_id/owner
    - 若缺，就新建 topic_id 並預設 owner=target_agent
    - 會把結果回灌到 state['topic_ctx']（若提供）
    """
    out = dict(args or {})

    # 從 state 推回（若可用）
    if state is not None:
        tc = (state.get("topic_ctx") or {})
        topic_id = tc.get("topic_id") or state.get("topic_id")
        owner = tc.get("owner") or state.get("owner") or target_agent
    else:
        topic_id = None
        owner = target_agent

    if not out.get("topic_id"):
        out["topic_id"] = topic_id or f"topic_{uuid.uuid4().hex[:8]}"
    out.setdefault("owner", owner)

    # 回灌到 state
    if state is not None:
        try:
            state.setdefault("topic_ctx", {})
            state["topic_ctx"].update({"topic_id": out["topic_id"], "owner": out["owner"]})
            if "RUN_ID" in os.environ:
                state["run_id"] = state.get("run_id") or os.environ["RUN_ID"]
        except Exception:
            pass

    return out


def _exec_one_tool(name: str, args: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """
    中央化工具呼叫 + 計時 + metrics 記錄（成功/失敗都會記）
    - name: 工具名稱（delegate_to_me / delegate_to_de / delegate_to_ds）
    - args: 工具參數（至少有 question 或 task）
    - state: 全域 state
    """
    t0_ms = int(time.time() * 1000)
    _ret: Dict[str, Any] = {}
    # --- 操弄檢核：首輪是否出現規劃/是否鎖 owner ---
    if state.get("turn_counter", 0) == 1 and name.startswith("delegate_to_"):
        # 視你的協定而定：若 args 中已有 owner/next_owner，就視為「鎖 owner」
        locked = bool(args.get("owner"))
        if not state.get("_plan_issued_marked"):
            emit_compliance(state=state, plan_issued_round=1, next_owner_locked=locked)
            state["_plan_issued_marked"] = True
    try:
        if name == "delegate_to_me":
            # 1) 確保 topic/owner（用 state 兜底）
            args = ensure_topic_in_args(args, target_agent="ME", state=state)

            # 2) 可選：允許外部覆寫 pdf_dir
            if args.get("pdf_dir"):
                state["pdf_dir"] = args["pdf_dir"]

            # 3) 正常呼叫（把 topic_id/owner 一起傳下去）
            _ret = delegate_to_me(
                question=args.get("question", ""),
                state=state,
                topic_id=args.get("topic_id"),
                owner=args.get("owner"),
                success_criteria=args.get("success_criteria"),
            )

            # 4) 顯式記交接事件（並帶 meta）
            emit_delegate_event(
                caller_agent=state.get("current_agent", "Supervisor"),
                target_agent="ME",
                topic_id=args["topic_id"],
                reason=args.get("question", ""),
                turn_index=state.get("turn_counter"),
                state=state
            )

        elif name == "delegate_to_de":
            args = ensure_topic_in_args(args, target_agent="DE", state=state)

            _ret = delegate_to_de(
                task=args.get("task", ""),
                state=state,
                topic_id=args.get("topic_id"),
                owner=args.get("owner"),
                success_criteria=args.get("success_criteria"),
            )

            emit_delegate_event(
                caller_agent=state.get("current_agent", "Supervisor"),
                target_agent="DE",
                topic_id=args["topic_id"],
                reason=args.get("task", ""),
                turn_index=state.get("turn_counter"),
                state=state
            )

        elif name == "delegate_to_ds":
            args = ensure_topic_in_args(args, target_agent="DS", state=state)

            _ret = delegate_to_ds(
                task=args.get("task", ""),
                state=state,
                topic_id=args.get("topic_id"),
                owner=args.get("owner"),
                success_criteria=args.get("success_criteria"),
            )

            emit_delegate_event(
                caller_agent=state.get("current_agent", "Supervisor"),
                target_agent="DS",
                topic_id=args["topic_id"],
                reason=args.get("task", ""),
                turn_index=state.get("turn_counter"),
                state=state
            )

        else:
            _ret = {"status": "error", "message": f"unknown tool {name}"}

        # —— 成功路徑：記錄工具事件（摘要最多 500 字）——
        try:
            if isinstance(_ret, (dict, list)):
                head = json.dumps(_ret, ensure_ascii=False)
            else:
                head = str(_ret)
            head = head[:500] if head else ""
            note_tool_event(
                state,
                tool_name=name,
                args=args or {},
                started_ms=t0_ms,
                latency_ms=int(time.time() * 1000) - t0_ms,
                raw_output=head
            )
        except Exception:
            # 記錄本身不影響主流程
            pass

        return _ret

    except Exception as e:
        # —— 失敗路徑：也要記錄一次工具事件 ——
        try:
            note_tool_event(
                state,
                tool_name=name,
                args=args or {},
                started_ms=t0_ms,
                latency_ms=int(time.time() * 1000) - t0_ms,
                raw_output=f"ERROR: {type(e).__name__}: {str(e)}"
            )
        except Exception:
            pass
        # 保持原本例外外拋行為，讓上層顯示堆疊與中斷
        raise


def _feedback_note(colleague_results: List[Dict[str, Any]]) -> str:
    lines = []
    for r in colleague_results:
        agent = r.get("agent", "?");
        summary = str(r.get("summary", "(no summary)"))
        lines.append(f"- From {agent}: {_trim(summary, 200)}")
    return "\n".join(lines) if lines else "(no updates from colleagues)"


# def route_and_execute(state: Dict[str, Any]) -> Dict[str, Any]:
#     msgs = state.get("messages", []);
#     last = msgs[-1] if msgs else None
#     if not isinstance(last, AIMessage) or not last.tool_calls: return {}
#
#     outputs: List[ToolMessage] = [];
#     total_p2p_hops = 0
#     for call in last.tool_calls:
#         name = call.get("name");
#         args = call.get("args") or {}
#         res = _exec_one_tool(name, args, state)
#
#         _consume_p2p_requests(res, state)
#
#         raw_summary = res.get("summary")
#         slim_payload = {
#             "agent": res.get("agent"),
#             "summary": _trim(raw_summary, MAX_SUMMARY_CHARS),
#             "df_payload": res.get("df_payload"),  # << 加這行
#             "delegate_requests": res.get("delegate_requests"),
#         }
#         slim_payload = {k: v for k, v in slim_payload.items() if v is not None}
#
#         if isinstance(raw_summary, str) and len(raw_summary) > MAX_SUMMARY_CHARS:
#             state.setdefault("violations", []).append(
#                 {"kind": "summary_truncated", "agent": res.get("agent"), "original_len": len(raw_summary)})
#
#         outputs.append(ToolMessage(name=name, tool_call_id=call.get("id", "call"),
#                                    content=json.dumps(slim_payload, ensure_ascii=False)))
#
#         if isinstance(res, dict) and res.get("delegate_requests"):
#             # P2P 循环
#             origin = (res.get("agent") or "").upper();
#             pending = list(res["delegate_requests"]);
#             hops = 0
#             while pending and hops < _MAX_P2P_HOPS:
#                 hops += 1;
#                 p2p_results: List[Dict[str, Any]] = [];
#                 next_round: List[Dict[str, Any]] = []
#                 while pending:
#                     req = pending.pop(0);
#                     to = (req.get("to") or "").upper();
#                     sub_name = f"delegate_to_{to.lower()}";
#                     sub_args = {"task": req.get("task", "")}
#                     if to == "ME": sub_args = {"question": req.get("task", "")}
#                     if sub_name not in ["delegate_to_me", "delegate_to_de", "delegate_to_ds"]:
#                         outputs.append(ToolMessage(name="router", tool_call_id="p2p", content=json.dumps(
#                             {"status": "error", "message": f"bad delegate target: {to}"})))
#                         continue
#                     # sub_res = _exec_one_tool(sub_name, sub_args, state)
#                     # 1) 確保 topic/owner
#                     sub_args = ensure_topic_in_args(sub_args, target_agent=to)
#                     # 2) 執行
#                     sub_res = _exec_one_tool(sub_name, sub_args, state)
#                     # 3) 落交接邊（origin 來自你上層的訊息：res.get("agent")）
#                     emit_delegate_event(
#                         caller_agent=origin,  # 這一輪的發出者
#                         target_agent=to,
#                         topic_id=sub_args["topic_id"],
#                         reason=sub_args.get("task", "") or sub_args.get("question", ""),
#                         turn_index=state.get("turn_counter"),
#                         state=state
#                     )
#                     p2p_results.append(sub_res);
#                     outputs.append(ToolMessage(name=sub_name, tool_call_id="p2p", content=json.dumps({k: v for k, v in {
#                         "agent": sub_res.get("agent"),
#                         "summary": _trim(sub_res.get("summary"), MAX_SUMMARY_CHARS)}.items() if v is not None})))
#                     if isinstance(sub_res, dict) and sub_res.get("delegate_requests"): next_round.extend(
#                         sub_res["delegate_requests"])
#                 # feedback = _feedback_note(p2p_results);
#                 # cont = continue_agent(origin, state, feedback);
#                 # outputs.append(ToolMessage(name=f"continue_{origin}", tool_call_id="p2p-feedback",
#                 #                            content=json.dumps(cont, ensure_ascii=False)))
#                 # pending = list(cont.get("delegate_requests", [])) + next_round;
#                 # total_p2p_hops += 1
#
#
#
#     state["messages"].extend(outputs);
#     state.setdefault("metrics", {}).setdefault("p2p_hops", 0);
#     state["metrics"]["p2p_hops"] += total_p2p_hops
#     return {"messages": outputs, "metrics": state["metrics"], "violations": state.get("violations", [])}


def route_and_execute(state: Dict[str, Any]) -> Dict[str, Any]:

    msgs = state.get("messages", [])
    last = msgs[-1] if msgs else None
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return {}

    state.setdefault("metrics", {}).setdefault("global_tool_calls", 0)
    bb_lock = threading.Lock()

    outputs: List[ToolMessage] = []
    total_p2p_hops = 0
    hit_cap = False  # [ADD] 觸發上限時用來跳出多層迴圈

    # Plan A: split calls into parallel-capable and serial groups
    parallel_calls = [c for c in last.tool_calls if c.get("name") in _PARALLEL_CAPABLE]
    serial_calls   = [c for c in last.tool_calls if c.get("name") not in _PARALLEL_CAPABLE]

    def _run_one_call(call) -> tuple:
        """Execute one tool call; return (call, res). Thread-safe for metrics counter."""
        name = call.get("name")
        args = call.get("args") or {}
        with bb_lock:
            res = _exec_one_tool(name, args, state)
        with _metrics_lock:
            state["metrics"]["global_tool_calls"] += 1
        _consume_p2p_requests(res, state)
        return call, res

    def _append_output(call, res):
        name = call.get("name")
        raw_summary = res.get("summary")
        slim_payload = {
            "agent": res.get("agent"),
            "summary": _trim(raw_summary, MAX_SUMMARY_CHARS),
            "df_payload": res.get("df_payload"),
            "delegate_requests": res.get("delegate_requests"),
        }
        slim_payload = {k: v for k, v in slim_payload.items() if v is not None}
        if isinstance(raw_summary, str) and len(raw_summary) > MAX_SUMMARY_CHARS:
            state.setdefault("violations", []).append(
                {"kind": "summary_truncated", "agent": res.get("agent"), "original_len": len(raw_summary)}
            )
        outputs.append(ToolMessage(
            name=name,
            tool_call_id=call.get("id", "call"),
            content=json.dumps(slim_payload, ensure_ascii=False)
        ))

    # Run parallel-capable calls concurrently (ME + DE in same Supervisor turn)
    if len(parallel_calls) > 1:
        if state["metrics"]["global_tool_calls"] >= MAX_GLOBAL_TOOL_CALLS:
            warn = {"status": "stopped", "reason": "global_tool_cap_reached", "cap": MAX_GLOBAL_TOOL_CALLS}
            outputs.append(ToolMessage(name="router", tool_call_id="cap", content=json.dumps(warn, ensure_ascii=False)))
            state["metrics"]["stop_reason"] = "global_tool_cap_reached"
            hit_cap = True
        else:
            with ThreadPoolExecutor(max_workers=len(parallel_calls)) as pool:
                futures = [pool.submit(_run_one_call, c) for c in parallel_calls]
                for future in as_completed(futures):
                    call, res = future.result()
                    _append_output(call, res)
    else:
        # Single parallel call falls through to serial path
        serial_calls = parallel_calls + serial_calls
        parallel_calls = []

    for call in ([] if hit_cap else serial_calls):
        name = call.get("name")
        args = call.get("args") or {}

        if state["metrics"]["global_tool_calls"] >= MAX_GLOBAL_TOOL_CALLS:
            warn = {"status": "stopped", "reason": "global_tool_cap_reached", "cap": MAX_GLOBAL_TOOL_CALLS}
            outputs.append(ToolMessage(name="router", tool_call_id="cap", content=json.dumps(warn, ensure_ascii=False)))
            state["metrics"]["stop_reason"] = "global_tool_cap_reached"
            break

        res = _exec_one_tool(name, args, state)
        with _metrics_lock:
            state["metrics"]["global_tool_calls"] += 1
        _consume_p2p_requests(res, state)
        _append_output(call, res)

        # ----------------------------
        # P2P 迴圈（維持你原本邏輯，僅加入去重 + 節流 + JSON-safe）
        # ----------------------------
        if isinstance(res, dict) and res.get("delegate_requests"):
            origin = _norm_agent_name(res.get("agent"))
            pending = list(res["delegate_requests"])
            hops = 0

            # 每回合本地去重與開單上限（不寫入全域 state，避免觀測偏移）
            seen_keys: Set[str] = set()
            open_count = 0

            while pending and hops < _MAX_P2P_HOPS:
                hops += 1
                p2p_results: List[Dict[str, Any]] = []
                next_round: List[Dict[str, Any]] = []

                # while pending:
                #     req = pending.pop(0)
                #
                #     # 1) 去重與節流（不更動主流程，只略過重複/超量）
                #     key = _dedup_key(req)
                #     if key in seen_keys or open_count >= _MAX_OPEN_REQS:
                #         outputs.append(ToolMessage(
                #             name="router",
                #             tool_call_id="p2p-dedup",
                #             content=json.dumps({
                #                 "status": "waiting",
                #                 "reason": "duplicate_or_throttled",
                #                 "req_key": key,
                #                 "to": _norm_agent_name(req.get("to")),
                #             }, ensure_ascii=False)
                #         ))
                #         continue
                #     seen_keys.add(key)
                #     open_count += 1
                #
                #     # 2) 原本的子委派邏輯（保持不動）
                #     to = (req.get("to") or "").upper()
                #     sub_name = f"delegate_to_{to.lower()}"
                #     sub_args = {"task": req.get("task", "")}
                #     if to == "ME":
                #         sub_args = {"question": req.get("task", "")}
                #     if sub_name not in ["delegate_to_me", "delegate_to_de", "delegate_to_ds"]:
                #         outputs.append(ToolMessage(
                #             name="router",
                #             tool_call_id="p2p",
                #             content=json.dumps({"status": "error", "message": f"bad delegate target: {to}"})
                #         ))
                #         continue
                #
                #     # 3) 確保 topic/owner（你原本的邏輯）
                #     sub_args = ensure_topic_in_args(sub_args, target_agent=to)
                #
                #     # 4) 執行
                #     sub_res = _exec_one_tool(sub_name, sub_args, state)
                #
                #     # 5) 記錄交接邊（你原本的事件）
                #     emit_delegate_event(
                #         caller_agent=origin,
                #         target_agent=to,
                #         topic_id=sub_args["topic_id"],
                #         reason=sub_args.get("task", "") or sub_args.get("question", ""),
                #         turn_index=state.get("turn_counter"),
                #         state=state
                #     )
                #
                #     # 6) 報告子結果（瘦身）
                #     p2p_results.append(sub_res)
                #     outputs.append(ToolMessage(
                #         name=sub_name,
                #         tool_call_id="p2p",
                #         content=json.dumps({
                #             k: v for k, v in {
                #                 "agent": sub_res.get("agent"),
                #                 "summary": _trim(sub_res.get("summary"), MAX_SUMMARY_CHARS),
                #             }.items() if v is not None
                #         }, ensure_ascii=False)
                #     ))
                #
                #     # 7) 拓展下一輪請求（若有）
                #     if isinstance(sub_res, dict) and sub_res.get("delegate_requests"):
                #         next_round.extend(sub_res["delegate_requests"])

                while pending:
                    # [ADD] 若已達上限，終止本回合 P2P
                    if state["metrics"]["global_tool_calls"] >= MAX_GLOBAL_TOOL_CALLS:
                        warn = {
                            "status": "stopped",
                            "reason": "global_tool_cap_reached",
                            "cap": MAX_GLOBAL_TOOL_CALLS,
                            "where": "p2p",
                            "hops": hops,
                        }
                        outputs.append(ToolMessage(
                            name="router",
                            tool_call_id="p2p-cap",
                            content=json.dumps(warn, ensure_ascii=False)
                        ))
                        state["metrics"]["stop_reason"] = "global_tool_cap_reached"
                        hit_cap = True
                        break  # 跳出 inner while pending

                    req = pending.pop(0)
                    # 1) 去重與節流（不更動主流程，只略過重複/超量）
                    key = _dedup_key(req)
                    if key in seen_keys or open_count >= _MAX_OPEN_REQS:
                        outputs.append(ToolMessage(
                            name="router",
                            tool_call_id="p2p-dedup",
                            content=json.dumps({
                                "status": "waiting",
                                "reason": "duplicate_or_throttled",
                                "req_key": key,
                                "to": _norm_agent_name(req.get("to")),
                            }, ensure_ascii=False)
                        ))
                        continue
                    seen_keys.add(key)
                    open_count += 1
                    # 2) 原本的子委派邏輯（保持不動）
                    to = (req.get("to") or "").upper()
                    sub_name = f"delegate_to_{to.lower()}"
                    sub_args = {"task": req.get("task", "")}
                    if to == "ME":
                        sub_args = {"question": req.get("task", "")}

                    if sub_name not in ["delegate_to_me", "delegate_to_de", "delegate_to_ds"]:
                        outputs.append(ToolMessage(
                            name="router",
                            tool_call_id="p2p",
                            content=json.dumps({"status": "error", "message": f"bad delegate target: {to}"})
                        ))
                        continue

                    # 1) 確保 topic/owner
                    sub_args = ensure_topic_in_args(sub_args, target_agent=to)

                    # [ADD] 執行前再次檢查（保守一點）
                    if state["metrics"]["global_tool_calls"] >= MAX_GLOBAL_TOOL_CALLS:
                        warn = {
                            "status": "stopped",
                            "reason": "global_tool_cap_reached",
                            "cap": MAX_GLOBAL_TOOL_CALLS,
                            "where": "p2p-before-exec",
                            "hops": hops,
                        }
                        outputs.append(ToolMessage(
                            name="router",
                            tool_call_id="p2p-cap",
                            content=json.dumps(warn, ensure_ascii=False)
                        ))
                        state["metrics"]["stop_reason"] = "global_tool_cap_reached"
                        hit_cap = True
                        break

                    # 2) 執行
                    sub_res = _exec_one_tool(sub_name, sub_args, state)

                    # [ADD] 執行後累加全局工具次數
                    try:
                        state["metrics"]["global_tool_calls"] += 1
                    except Exception:
                        state.setdefault("metrics", {})["global_tool_calls"] = int(
                            state.get("metrics", {}).get("global_tool_calls", 0)
                        ) + 1

                    # 3) 落交接邊（origin 來自你上層的訊息：res.get("agent")）
                    emit_delegate_event(
                        caller_agent=origin,
                        target_agent=to,
                        topic_id=sub_args["topic_id"],
                        reason=sub_args.get("task", "") or sub_args.get("question", ""),
                        turn_index=state.get("turn_counter"),
                        state=state
                    )

                    p2p_results.append(sub_res)
                    outputs.append(ToolMessage(
                        name=sub_name,
                        tool_call_id="p2p",
                        content=json.dumps(
                            {
                                k: v for k, v in {
                                "agent": sub_res.get("agent"),
                                "summary": _trim(sub_res.get("summary"), MAX_SUMMARY_CHARS)
                            }.items() if v is not None
                            },
                            ensure_ascii=False
                        )
                    ))

                    if isinstance(sub_res, dict) and sub_res.get("delegate_requests"):
                        next_round.extend(sub_res["delegate_requests"])

                if hit_cap:
                    break

                # 8) 回饋與續問：沿用你原本設計，但用 JSON-safe 包裹，避免 HumanMessage 序列化錯誤
                feedback = _feedback_note(p2p_results)
                cont = continue_agent(origin, state, feedback)
                outputs.append(ToolMessage(
                    name=f"continue_{origin}",
                    tool_call_id="p2p-feedback",
                    content=json.dumps(_json_safe(cont), ensure_ascii=False)
                ))

                # 9) 下一輪 pending
                pending = list((cont or {}).get("delegate_requests", [])) + next_round
                total_p2p_hops += 1

    state["messages"].extend(outputs)
    state.setdefault("metrics", {}).setdefault("p2p_hops", 0)
    state["metrics"]["p2p_hops"] += total_p2p_hops
    return {"messages": outputs, "metrics": state["metrics"], "violations": state.get("violations", [])}
