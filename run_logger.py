# # run_logger.py
import os, json, time, hashlib, atexit, uuid, traceback
from contextlib import contextmanager
from typing import Any, Dict, Optional, List
from common import ensure_run_id



def _now_ms() -> int: return int(time.time() * 1000)


def new_uuid(prefix: str = "ev") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

# def _runs_root() -> str:
#     root = "/mnt/data/runs"
#     os.makedirs(root, exist_ok=True)
#     return root
#
# def _runs_dir() -> str:
#     root = "/mnt/data/runs"
#     os.makedirs(root, exist_ok=True)
#     return root

def _root() -> str:
    # 可用環境變數覆寫；預設 /mnt/data/runs
    root = os.environ.get("RUNS_DIR", "/mnt/data/runs")
    os.makedirs(root, exist_ok=True)
    return root

def _run_dir(state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> str:
    rid = _resolve_run_id(state, run_id)
    d = os.path.join(_root(), rid)
    os.makedirs(d, exist_ok=True)
    return d

def _path_runmeta(state=None, run_id=None) -> str:
    return os.path.join(_run_dir(state, run_id), "run_meta.json")

def _path_outcome(state=None, run_id=None) -> str:
    return os.path.join(_run_dir(state, run_id), "outcome.json")

def _path_events(state=None, run_id=None) -> str:
    return os.path.join(_run_dir(state, run_id), "events.jsonl")

def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

# def _events_path(run_id: str) -> str:
#     d = os.path.join(_runs_root(), run_id)
#     os.makedirs(d, exist_ok=True)
#     return os.path.join(d, "events.jsonl")

def _resolve_run_id(state: Optional[Dict[str, Any]] = None,
                    run_id: Optional[str] = None) -> str:
    """盡量從 run_id → state → common.ensure_run_id(state) → 環境變數 → fallback 取得 run_id"""
    if run_id:
        return run_id
    if state:
        # 常見放法：state["RUN_ID"] 或 state.get("run_id")
        for k in ("RUN_ID", "run_id", "id"):
            if isinstance(state, dict) and state.get(k):
                return str(state[k])
        if ensure_run_id:
            try:
                rid = ensure_run_id(state)
                if rid:
                    return str(rid)
            except Exception:
                pass
    rid = os.environ.get("RUN_ID")
    if rid:
        return rid
    return "unknown_run"


def emit_event(e: Dict[str, Any],
               *,
               state: Optional[Dict[str, Any]] = None,
               run_id: Optional[str] = None) -> None:
    """寫入一列事件到 /runs/{run_id}/events.jsonl"""
    rid = _resolve_run_id(state=state, run_id=run_id)
    e = dict(e or {})
    e.setdefault("run_id", rid)
    e.setdefault("event_id", new_uuid())
    e.setdefault("timestamp", _now_ms())
    e.setdefault("turn_index", e.get("turn_index", None))
    e.setdefault("channel", e.get("channel", "team"))
    assert "event_type" in e and "agent" in e, "event_type/agent 必填"
    # path = _events_path(rid)
    path = _path_events(state, rid)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")


def log_message(*,
                agent: str,
                content_text: str,
                topic_id: Optional[str] = None,
                addressed_to: str = "",
                turn_index: Optional[int] = None,
                channel: str = "team",
                state: Optional[Dict[str, Any]] = None,
                run_id: Optional[str] = None) -> None:
    """在 AIMessage 產生後、呼叫工具前記一列 message 事件"""
    emit_event({
        "event_type": "message",
        "agent": agent,
        "addressed_to": addressed_to or "",
        "topic_id": topic_id or "",
        "content_text": (content_text or "")[:800],
        "turn_index": turn_index,
        "channel": channel
    }, state=state, run_id=run_id)

def _hash_file(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""): h.update(chunk)
        return h.hexdigest()[:12]
    except Exception:
        return None

class RunLogger:
    def __init__(self, run_id: str, out_json_path: str):
        self.run_id = run_id
        self.out_json_path = out_json_path
        self.data: Dict[str, Any] = {
            "schema_version":"2.0", "run_id": run_id,
            "policy": None, "model_params": {}, "prompt_versions": {},
            "tasks": [], "node_events": [], "tool_events": [],
            "error_events": [], "open_issues": [], "artifacts": [], "consistency_checks": [],
            "messages": [], "blackboard": {}, "metrics": {}, "tool_events_legacy":[]
        }
        atexit.register(self.flush)

    def set_policy(self, policy:str): self.data["policy"]=policy
    def set_model_params(self, **kw): self.data["model_params"].update(kw)
    def set_prompt_versions(self, role_to_path: Dict[str,str]):
        self.data["prompt_versions"] = {r:{"hash":_hash_file(p),"path":p} for r,p in (role_to_path or {}).items()}

    def new_task(self, by:str, to:str, instruction:str, parent_task_id:Optional[str]=None)->str:
        tid=f"t-{uuid.uuid4().hex[:8]}"; now=_now_ms()
        self.data["tasks"].append({"task_id":tid,"parent_task_id":parent_task_id,"by":by,"to":to,
                                   "instruction":instruction,"ts_start_ms":now,"ts_end_ms":None,
                                   "llm_latency_ms":None,"status":"delegated"})
        return tid

    def close_task(self, task_id:str, status:str="done", llm_latency_ms:Optional[int]=None):
        for t in reversed(self.data["tasks"]):
            if t["task_id"]==task_id and t["ts_end_ms"] is None:
                t["ts_end_ms"]=_now_ms(); t["status"]=status; t["llm_latency_ms"]=llm_latency_ms; return

    @contextmanager
    def agent_node(self, agent:str, task_id:str):
        t0=_now_ms(); self.data["node_events"].append({"agent":agent,"node":agent,"event":"enter","ts_ms":t0,"task_id":task_id})
        try:
            yield
        finally:
            t1=_now_ms(); self.data["node_events"].append({"agent":agent,"node":agent,"event":"exit","ts_ms":t1,"task_id":task_id,"llm_latency_ms":t1-t0})

    @contextmanager
    def tool_exec(self, agent:str, tool:str, task_id:Optional[str]=None, args:Optional[Dict]=None, section:Optional[str]=None):
        t0=_now_ms(); ok=None
        class _Ctx:
            def ok(self, v:bool):
                nonlocal ok; ok=bool(v)
        ctx=_Ctx()
        try:
            yield ctx
        finally:
            self.data["tool_events"].append({"task_id":task_id,"agent":agent,"tool":tool,
                                             "t_start_ms":t0,"latency_ms":_now_ms()-t0,"ok":ok,"section":section,"args":args or {}})

    def artifact(self, task_id:str, type_:str, path_or_hash:Optional[str]=None, preview_stats:Optional[Dict]=None):
        aid=f"af-{uuid.uuid4().hex[:6]}"; self.data["artifacts"].append(
            {"artifact_id":aid,"task_id":task_id,"type":type_,"path_or_hash":path_or_hash,"preview_stats":preview_stats}); return aid

    def error_event(self, agent:str, kind:str, message:str, task_id:Optional[str]=None, recovered:Optional[bool]=None, recovery_steps:Optional[int]=None, exc:Exception=None):
        self.data["error_events"].append({"task_id":task_id,"agent":agent,"kind":kind,"message":message,"ts_ms":_now_ms(),
                                          "recovered":recovered,"recovery_steps":recovery_steps,
                                          "stack":"".join(traceback.format_exception(type(exc),exc,exc.__traceback__)) if exc else None})

    def open_issue(self, by:str, owner:str, summary:str, severity:str="blocking", status:str="open"):
        iid=f"iss-{uuid.uuid4().hex[:6]}"; now=_now_ms()
        self.data["open_issues"].append({"issue_id":iid,"by":by,"owner":owner,"severity":severity,
                                         "status":status,"first_ts":now,"resolved_ts":None,"summary":summary}); return iid

    def resolve_issue(self, issue_id:str):
        for x in reversed(self.data["open_issues"]):
            if x["issue_id"]==issue_id and x["resolved_ts"] is None: x["status"]="resolved"; x["resolved_ts"]=_now_ms(); return

    def consistency_check(self, check:str, target:str, blackboard, summary, passed:bool):
        self.data["consistency_checks"].append({"check":check,"target":target,"blackboard":blackboard,"summary":summary,"pass":bool(passed)})

    def attach_legacy(self, key:str, value): self.data[key]=value

    def flush(self):
        try:
            out_dir=f"/mnt/data/runs/{self.run_id}"; os.makedirs(out_dir, exist_ok=True)
            with open(self.out_json_path, "w", encoding="utf-8") as f: json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception: pass

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
    meta.setdefault("start_time_ms", _now_ms())
    emit_run_meta(state, run_id, **meta)

def end_run(state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> None:
    emit_run_meta(state, run_id, end_time_ms=_now_ms())

# ========= Event 級 =========
def emit_event(e: Dict[str, Any], *, state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> None:
    """每一個行為一列事件：delegate/message/tool_call/bb_write/bb_read/plan_* 等"""
    rid = _resolve_run_id(state, run_id)
    e = dict(e or {})
    e.setdefault("run_id", rid)
    e.setdefault("event_id", new_uuid())
    e.setdefault("timestamp", _now_ms())
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
        "channel": channel
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
        "turn_index": turn_index
    }, state=state)

# ========= Blackboard 讀寫 =========
def emit_bb_write(*, agent: str, topic_id: str, section: str, artifact_id: str,
                  uri: str = "", intended_owner: str = "",
                  turn_index: Optional[int] = None,
                  state: Optional[Dict[str, Any]] = None) -> None:
    print(f"DEBUG: >>> EMIT_BB_WRITE CALLED by {agent} for section {section}! <<<")
    emit_event({
        "event_type": "bb_write",
        "agent": agent, "addressed_to": "",
        "topic_id": topic_id, "bb_section": section,
        "bb_write_id": artifact_id, "artifact_uri": uri,
        "intended_owner": intended_owner, "turn_index": turn_index
    }, state=state)

def emit_bb_read(*, agent: str, topic_id: str, section: str,
                 fact_ids_served: List[str],
                 turn_index: Optional[int] = None,
                 state: Optional[Dict[str, Any]] = None) -> None:
    print(f"DEBUG: >>> EMIT_BB_READ CALLED by {agent} for section {section}! <<<")
    # 多個 id 可各寫一列（或合併一列帶清單，ETL 時展開）
    if not fact_ids_served:
        fact_ids_served = []
    for fx in fact_ids_served:
        emit_event({
            "event_type": "bb_read",
            "agent": agent, "addressed_to": "",
            "topic_id": topic_id, "bb_section": section,
            "bb_read_of": fx, "turn_index": turn_index
        }, state=state)

# ========= Compliance / Outcome =========
def emit_compliance(*, state: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None, **kv) -> None:
    emit_event({
        "event_type": "compliance",
        "agent": "System", "addressed_to": "",
        **kv
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
        "written_at_ms": _now_ms()
    }
    with open(_path_outcome(state, run_id), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 也落一列事件
    emit_event({
        "event_type": "outcome",
        "agent": "System", "addressed_to": "",
        **out
    }, state=state, run_id=run_id)

_LOGGERS = {}
def get_run_logger():
    rid = os.getenv("RUN_ID", "default")
    out = f"/mnt/data/runs/{rid}/run.json"
    if rid not in _LOGGERS: _LOGGERS[rid] = RunLogger(rid, out)
    return _LOGGERS[rid]



