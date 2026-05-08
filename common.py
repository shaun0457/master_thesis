import os, time, json, traceback, operator, copy, uuid, random, hashlib
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
import atexit, signal


# ===== LLM config from env =====
_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
_TEMP  = float(os.getenv("GEMINI_TEMP", "0.25"))
VERBOSE = os.getenv("MAS_VERBOSE", "1") == "1"


llm = ChatGoogleGenerativeAI(
    model=_MODEL,
    temperature=_TEMP,
    max_output_tokens=8192,
)

def get_env_int(name: str, default: int) -> int:
    """從環境變數讀 int；缺值或格式錯誤就回 default。"""
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _hash_to_int(s: str, max_int: int = 2**31-1) -> int:
    h = hashlib.sha256((s or "").encode("utf-8")).hexdigest()
    return int(h[:8], 16) % max_int

def derive_seed(run_id: Optional[str], task_id: Optional[str], fallback: int = 11) -> int:
    """
    若未手動給 SEED，依 run_id + task_id 決定性衍生一個種子。
    - 同一 (run_id, task_id) 會得到固定種子
    - 沒有 run_id 時回傳 fallback
    """
    rid = (run_id or "").strip()
    tid = (task_id or "").strip()
    if not rid:
        return fallback
    return _hash_to_int(f"{rid}::{tid or ''}")

def get_seed(state: Optional[dict] = None, default: int = 11) -> int:
    """
    取用優先序：
    1) state['seed']
    2) 環境變數 SEED
    3) 由 (RUN_ID, TASK_ID) 自動推導
    4) default
    """
    if isinstance(state, dict) and "seed" in state:
        try:
            return int(state["seed"])
        except Exception:
            pass
    try:
        return int(os.getenv("SEED", ""))
    except Exception:
        pass
    rid = os.getenv("RUN_ID", (state or {}).get("run_id") if state else None)
    tid = os.getenv("TASK_ID", (state or {}).get("task_id") if state else None)
    return derive_seed(rid, tid, fallback=default)

def set_global_seeds(seed: int) -> None:
    """固定 Python/NumPy/（可選）其他 lib 的亂數源。"""
    try:
        random.seed(seed)
    except Exception:
        pass
    try:
        import numpy as np
        np.random.seed(seed % (2**32 - 1))
    except Exception:
        pass
    # 其他框架（如 torch）可在這裡加

def dbg(*args):
    if VERBOSE:
        print("[DBG]", *args)

def dbg_json(title: str, obj, maxlen: int = 800):
    if not VERBOSE:
        return
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    except Exception:
        s = str(obj)
    if len(s) > maxlen:
        s = s[:maxlen] + " ...<trunc>"
    print(f"[DBG] {title}: {s}")

# ===== Shared state (兼容所有 Stage-1 实验) =====
class AgentState(TypedDict, total=False):
    """
    一个兼容所有第一阶段实验的通用状态定义。
    total=False 使得所有键都变为可选，从而允许不同实验使用不同的状态子集。
    """
    messages: Annotated[List[BaseMessage], operator.add]
    # ME & DS 实验使用
    hits: List[Dict[str, Any]]
    # DE (实验 1.1) 专用
    task_stack: List[Dict[str, Any]]
    task_contract: Dict[str, Any]
    # 通用监控
    tool_events: List[Dict[str, Any]]
    metrics: Dict[str, Any]

# ===== 日志记录辅助 =====
def _msg_to_dict(msg: BaseMessage) -> dict:
    """将 LangChain 消息对象转换为可序列化字典（健壮版）。"""
    try:
        if isinstance(msg, HumanMessage):
            return {"type": "human", "content": msg.content}
        if isinstance(msg, AIMessage):
            tool_calls = []
            for tc in (getattr(msg, "tool_calls", None) or []):
                # 兼容 dict 或具属性的对象
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
                _id  = tc.get("id")   if isinstance(tc, dict) else getattr(tc, "id", None)
                tool_calls.append({"name": name, "args": args, "id": _id})
            return {"type": "ai", "content": msg.content, "tool_calls": tool_calls}
        if isinstance(msg, ToolMessage):
            return {
                "type": "tool",
                "content": msg.content,
                "name": getattr(msg, "name", None),
                "tool_call_id": getattr(msg, "tool_call_id", None),
            }
        return {"type": "system", "content": str(msg)}
    except Exception:
        return {"type": msg.__class__.__name__, "content": getattr(msg, "content", str(msg))}

# ===== 实验执行与落盘（崩溃保底 + 1.2 相容格式） =====
def run_and_log_experiment(
    graph,
    initial_state: dict,
    run_id: str,
    log_directory: str = "experiment_logs",
    recursion_limit: int = 50,
):
    """
    统一的实验运行器：
    - 完整记录 final_logbook（list 形状，兼容 1.2 分析器）
    - 追加每一步 node 的完成事件到 tool_events，供 Manipulation Check
    - 崩溃也会保底落盘；返回 (latest_state, log_data)
    """
    print(f"\n{'=' * 25} 开始运行实验: {run_id} {'=' * 25}")
    os.environ["RUN_ID"] = run_id
    os.makedirs(log_directory, exist_ok=True)
    final_path = os.path.join(log_directory, f"{run_id}.json")

    start_ts = time.time()
    status_runtime = "UNKNOWN"
    latest_state: Optional[dict] = None
    tool_events_accum: List[Dict[str, Any]] = []  # 跨步骤累积事件

    def _initial_question() -> str:
        msgs = initial_state.get("messages") or []
        if msgs:
            m0 = msgs[0]
            return getattr(m0, "content", str(m0))
        return "N/A"

    def _build_log_data(final_state: Optional[dict]) -> dict:
        state = final_state if final_state is not None else initial_state
        messages_list = [_msg_to_dict(m) for m in (state.get("messages") or [])]
        metrics_obj   = state.get("metrics") or {}
        tool_events   = state.get("tool_events") or []
        duration      = round(time.time() - start_ts, 2)

        data = {
            "run_id": run_id,
            "status_runtime": status_runtime,               # 运行时态：COMPLETED / CRASHED:...
            "status_verdict": metrics_obj.get("ds_verdict"),# DS 评审态
            "status": metrics_obj.get("ds_verdict") or status_runtime,  # 兼容字段
            "duration_seconds": duration,
            "initial_question": _initial_question(),
            "final_logbook": messages_list,                 # ★ 直接 list（1.2 需要）
            "metrics": metrics_obj,
            "tool_events": tool_events,
        }
        return data

    try:
        if graph is None or not hasattr(graph, "stream"):
            raise RuntimeError("Graph is not compiled.")

        for output in graph.stream(initial_state, {"recursion_limit": recursion_limit}):
            # LangGraph: 每次产出一个 {node_name: state_snapshot}
            node, snapshot = list(output.items())[0]
            print(f">>> 步骤: '{node}' 完成")

            # 1) 累积工具事件（避免被后续覆盖）
            step_events = snapshot.get("tool_events") or []
            if isinstance(step_events, list):
                tool_events_accum.extend(step_events)

            # 2) 记录节点完成事件（供 Manipulation Check）
            tool_events_accum.append({"event": "node_completed", "node": node, "ts": time.time()})
            snapshot["tool_events"] = copy.deepcopy(tool_events_accum)

            # 3) 直接采用「最新快照」作为 messages 的来源（避免重复膨胀）
            latest_state = copy.deepcopy(snapshot)

        status_runtime = "COMPLETED"
        print(f"--- 实验 {run_id} 流程完成 ---")
    except Exception as e:
        status_runtime = f"CRASHED: {type(e).__name__}"
        print(f"--- !!! 实验 {run_id} 崩溃 !!! ---")
        print(f"错误讯息: {e}")
        traceback.print_exc()
    finally:
        log_data = _build_log_data(latest_state)
        with open(final_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"--- 日志已储存至: {final_path} ---")

    return latest_state, log_data

# def run_and_log_experiment(
#     graph,
#     initial_state: dict,
#     run_id: str,
#     log_directory: str = "experiment_logs",
#     recursion_limit: int = 50,
# ):
#     """
#     统一的实验运行器（強化版）：
#     - 完整记录 final_logbook（list 形状，兼容 1.2 分析器）
#     - 追加每一步 node 的完成事件到 tool_events，供 Manipulation Check
#     - 崩溃 / Ctrl+C / 結束也會保底落盘；返回 (latest_state, log_data)
#     """
#     print(f"\n{'=' * 25} 开始运行实验: {run_id} {'=' * 25}")
#     os.environ["RUN_ID"] = run_id
#     os.makedirs(log_directory, exist_ok=True)
#     final_path = os.path.join(log_directory, f"{run_id}.json")
#
#     start_ts = time.time()
#     status_runtime = "UNKNOWN"
#     latest_state: Optional[dict] = None
#     tool_events_accum: List[Dict[str, Any]] = []  # 跨步骤累积事件
#     _already_flushed = {"done": False}  # 防重入
#
#     def _json_safe_local(obj):
#         # 足夠用的容錯序列化（避免 HumanMessage/AIMessage 炸掉）
#
#         if isinstance(obj, (str, int, float, bool)) or obj is None:
#             return obj
#         if isinstance(obj, (list, tuple)):
#             return [_json_safe_local(x) for x in obj]
#         if isinstance(obj, dict):
#             return {str(k): _json_safe_local(v) for k, v in obj.items()}
#         if isinstance(obj, (HumanMessage, AIMessage, SystemMessage, ToolMessage)):
#             base = {"type": obj.__class__.__name__, "content": getattr(obj, "content", None)}
#             if hasattr(obj, "name"):
#                 base["name"] = getattr(obj, "name", None)
#             return base
#         return str(obj)
#
#     def _initial_question() -> str:
#         msgs = initial_state.get("messages") or []
#         if msgs:
#             m0 = msgs[0]
#             return getattr(m0, "content", str(m0))
#         return "N/A"
#
#     def _build_log_data(final_state: Optional[dict]) -> dict:
#         state = final_state if final_state is not None else initial_state
#         messages_list = [_msg_to_dict(m) for m in (state.get("messages") or [])]
#         metrics_obj   = state.get("metrics") or {}
#         tool_events   = state.get("tool_events") or []
#         duration      = round(time.time() - start_ts, 2)
#
#         data = {
#             "run_id": run_id,
#             "status_runtime": status_runtime,               # 运行时态：COMPLETED / CRASHED:...
#             "status_verdict": metrics_obj.get("ds_verdict"),# DS 评审态
#             "status": metrics_obj.get("ds_verdict") or status_runtime,  # 兼容字段
#             "duration_seconds": duration,
#             "initial_question": _initial_question(),
#             "final_logbook": messages_list,                 # ★ 直接 list（1.2 需要）
#             "metrics": metrics_obj,
#             "tool_events": tool_events,
#         }
#         return data
#
#     def _safe_flush_and_save(final_state: Optional[dict]):
#         if _already_flushed["done"]:
#             return
#         _already_flushed["done"] = True
#         log_data = _build_log_data(final_state)
#         try:
#             with open(final_path, "w", encoding="utf-8") as f:
#                 json.dump(log_data, f, ensure_ascii=False, indent=2, default=_json_safe_local)
#             print(f"--- 日志已储存至: {final_path} ---")
#         except Exception as e:
#             print(f"[WARN] 无法写入日志文件：{e}")
#
#     # 註冊保底
#     atexit.register(lambda: _safe_flush_and_save(latest_state))
#     for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
#         if sig is not None:
#             signal.signal(sig, lambda *_: (_safe_flush_and_save(latest_state), sys.exit(1)))
#
#     try:
#         if graph is None or not hasattr(graph, "stream"):
#             raise RuntimeError("Graph is not compiled.")
#
#         for output in graph.stream(initial_state, {"recursion_limit": recursion_limit}):
#             # LangGraph: 每次产出一个 {node_name: state_snapshot}
#             node, snapshot = list(output.items())[0]
#             print(f">>> 步骤: '{node}' 完成")
#
#             # 1) 累积工具事件（避免被后续覆盖）
#             step_events = snapshot.get("tool_events") or []
#             if isinstance(step_events, list):
#                 tool_events_accum.extend(step_events)
#
#             # 2) 记录节点完成事件（供 Manipulation Check）
#             tool_events_accum.append({"event": "node_completed", "node": node, "ts": time.time()})
#             snapshot["tool_events"] = copy.deepcopy(tool_events_accum)
#
#             # 3) 直接采用「最新快照」作为 messages 的来源（避免重复膨胀）
#             latest_state = copy.deepcopy(snapshot)
#
#         status_runtime = "COMPLETED"
#         print(f"--- 实验 {run_id} 流程完成 ---")
#     except BaseException as e:  # 抓到 KeyboardInterrupt / SystemExit 也會寫入原因
#         status_runtime = f"CRASHED: {type(e).__name__}"
#         print(f"--- !!! 实验 {run_id} 崩溃 !!! ---")
#         print(f"错误讯息: {e}")
#         traceback.print_exc()
#     finally:
#         _safe_flush_and_save(latest_state)
#
#     return latest_state, _build_log_data(latest_state)
# ==== Blackboard SDK (capability, not enforcement) ====

def _bb(state: dict) -> dict:
    """确保 state 中存在 blackboard 字典并返回其引用。"""
    bb = state.setdefault("blackboard", {})
    bb.setdefault("facts", [])
    bb.setdefault("datasets", [])
    bb.setdefault("citations", [])
    bb.setdefault("open_issues", [])
    return bb


def bb_merge(state: dict, *, facts: list = None, datasets: list = None, citations: list = None,
             open_issues: list = None):
    """
    非破坏性地将新的条目合并到黑板的指定部分。
    使用 JSON 字符串来去重，确保条目的唯一性。
    """
    bb = _bb(state)
    for key, items in [("facts", facts), ("datasets", datasets), ("citations", citations),
                       ("open_issues", open_issues)]:
        if not items:
            continue
        # 为了去重，我们只比较核心内容，忽略每次都不同的元数据（如时间戳）
        # 这里使用一个简化的方法，未来可以做得更精细
        current_items_str = {json.dumps(item, sort_keys=True) for item in bb[key]}
        for item in items:
            item_str = json.dumps(item, sort_keys=True)
            if item_str not in current_items_str:
                bb[key].append(item)


def bb_latest_dataset_uri(state: dict) -> str | None:
    """返回黑板上最新的一个数据集的 df_payload 路径。"""
    bb = _bb(state)
    # 从后往前找，找到第一个有效的路径
    for item in reversed(bb.get("datasets", [])):
        uri = item.get("df_payload") or item.get("dataset_uri")
        if uri and isinstance(uri, str):
            return uri
    return None




def bb_snapshot_text(state: dict, max_items: int = 3) -> str:
    """为 LLM 生成一个可读的、简洁的黑板快照文本。
    - 保持原有輸出格式與邏輯
    - 額外把檔案黑板（/runs/<RUN_ID>/blackboard/registry.json）尾端資料合併進 snapshot
    """
    # 1) 原本的 in-memory 黑板（沿用你的現有邏輯）
    try:
        bb_mem = _bb(state) or {}
    except Exception:
        bb_mem = {}

    # 2) 檔案黑板（單一事實來源）
    bb_file = {}
    try:
        from bb_tools import get_bb_snapshot as _bb_get_snapshot  # 只讀，不影響現有寫入
        run_id = (state or {}).get("run_id") or os.environ.get("RUN_ID")
        if _bb_get_snapshot:
            bb_file = _bb_get_snapshot(run_id) or {}
    except Exception:
        bb_file = {}

    def _tail(items):
        items = list(items or [])
        return list(reversed(items))[:max_items] if max_items and max_items > 0 else list(reversed(items))

    # 3) 合併（datasets / facts / open_issues），用簡單 key 去重
    def _dedup_merge(section: str):
        seen = set()
        merged = []

        # 先推入 file，再推入 mem（靠近回合的內容會排在前面）
        for src in (_tail(bb_file.get(section)), _tail(bb_mem.get(section))):
            for it in src:
                if not isinstance(it, dict):
                    continue
                key = it.get("artifact_id") or it.get("uri") or it.get("ref") or it.get("df_payload") or it.get("preview") or it.get("summary") or str(it)[:120]
                if key in seen:
                    continue
                seen.add(key)
                merged.append(it)
        return merged[:max_items] if max_items and max_items > 0 else merged

    ds_items   = _dedup_merge("datasets")
    fact_items = _dedup_merge("facts")
    iss_items  = _dedup_merge("open_issues")

    # 4) 映射到你原本的輸出欄位（不改格式）
    lines = ["[Blackboard Snapshot -- for your context only, read-only]"]

    if ds_items:
        lines.append("--- Recent Datasets ---")
        for item in ds_items:
            # 找 URI：依序取 df_payload/path/ref/uri/dataset_uri
            uri = None
            dfp = item.get("df_payload")
            if isinstance(dfp, dict):
                uri = dfp.get("path") or dfp.get("ref")
            if not uri:
                uri = item.get("ref") or item.get("uri") or item.get("dataset_uri")
            if not uri and isinstance(dfp, str):
                uri = dfp
            lines.append(f"- URI: {uri}")
            # Summary：優先 name/preview/summary
            sm = item.get("name") or item.get("preview") or item.get("summary")
            if sm:
                lines.append(f"  Summary: {str(sm)[:100]}...")

    if fact_items:
        lines.append("--- Recent Facts ---")
        for item in fact_items:
            # Summary：優先 summary/preview
            sm = item.get("summary") or item.get("preview") or str(item)
            ag = item.get("agent") or item.get("created_by") or "?"
            lines.append(f"- (from {ag}): {str(sm)[:120]}...")

    if iss_items:
        lines.append("--- Open Issues ---")
        for item in iss_items:
            ag = item.get("agent") or item.get("created_by") or "?"
            err = item.get("error") or item.get("preview") or str(item)
            lines.append(f"- (from {ag}): {str(err)[:100]}...")

    if len(lines) == 1:
        return "[Blackboard Snapshot -- currently empty]"
    return "\n".join(lines)


def ensure_run_id(state: dict) -> str:
    """
    確保整個流程只使用同一個 RUN_ID：
    - 只在外層沒有 run_id 時才新建
    - 永遠把 state["run_id"] 與 os.environ["RUN_ID"] 對齊
    - 回傳最終使用的 run_id
    """
    rid = state.get("run_id") or os.getenv("RUN_ID")
    if not rid:
        rid = f"run_{uuid.uuid4().hex[:8]}"
        state["run_id"] = rid
    else:
        state["run_id"] = rid
    os.environ["RUN_ID"] = str(rid)
    return rid


