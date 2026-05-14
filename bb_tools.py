# bb_tools.py — File-backed blackboard (single source of truth) with stable artifact_id
# 安全覆蓋舊版使用；不依賴 common.ensure_run_id

import os, json, time, uuid, hashlib, threading
from typing import Any, Dict, List, Optional
import pandas as pd
from langchain.tools import tool
from run_logger import emit_bb_write, emit_bb_read, note_tool_call

BLACKBOARD_LOCK = threading.RLock()

# ========= basic helpers =========

def now_ms() -> int:
    return int(time.time() * 1000)

def _root() -> str:
    """Blackboard 根目錄，可用環境變數 RUNS_DIR 覆寫。"""
    root = os.environ.get("RUNS_DIR", "/mnt/data/runs")
    os.makedirs(root, exist_ok=True)
    return root

def _resolve_run_id(run_id: Optional[str] = None) -> str:
    """優先使用傳入的 run_id；否則取環境變數 RUN_ID；最後 fallback 'default'。"""
    return (run_id or os.environ.get("RUN_ID") or "default")

def _bb_path(run_id: Optional[str] = None) -> str:
    rid = _resolve_run_id(run_id)
    d = os.path.join(_root(), rid, "blackboard")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "registry.json")

def _ensure_structure(reg: Dict[str, Any]) -> Dict[str, Any]:
    reg = dict(reg or {})
    reg.setdefault("facts", [])
    reg.setdefault("datasets", [])
    reg.setdefault("citations", [])
    reg.setdefault("open_issues", [])
    reg.setdefault("artifacts", [])   # 扁平索引（各 section 的摘要）
    return reg

def _load(run_id: Optional[str] = None) -> Dict[str, Any]:
    p = _bb_path(run_id)
    if not os.path.exists(p):
        return _ensure_structure({})
    try:
        with open(p, "r", encoding="utf-8") as f:
            return _ensure_structure(json.load(f))
    except Exception:
        return _ensure_structure({})

def _save(run_id: Optional[str], reg: Dict[str, Any]) -> None:
    with open(_bb_path(run_id), "w", encoding="utf-8") as f:
        json.dump(_ensure_structure(reg), f, ensure_ascii=False, indent=2)

def _mk_artifact_id(seed: str, prefix: str = "fx") -> str:
    """用 deterministic hash 產生穩定 ID；不同內容/時間種子會不同。"""
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{h}"


def _fact_entry(
    claim: str,
    agent: str = "unknown",
    source_tool: str = "unknown",
    confidence: float = 1.0,
    turn: Optional[int] = None,
) -> Dict[str, Any]:
    """Canonical provenance dict for a blackboard fact."""
    return {
        "claim": claim,
        "agent": agent,
        "source_tool": source_tool,
        "confidence": confidence,
        "turn": turn,
    }

# ========= core programmatic API (供代理/程式碼呼叫) =========

# def bb_write(*, run_id: Optional[str],
#              topic_id: str,
#              section: str,
#              content_preview: str,
#              created_by: str,
#              uri: str = "",
#              intended_owner: str = "") -> Dict[str, Any]:
#     """
#     寫一筆到 blackboard（facts / datasets / citations / open_issues）
#     回傳: {"status":"ok","artifact_id":..., "topic_id":..., "section":..., "uri":...}
#     """
#
#     rid = _resolve_run_id(run_id)
#     reg = _load(rid)
#     seed = f"{rid}|{topic_id}|{section}|{(content_preview or '')[:64]}|{time.time()}"
#     artifact_id = _mk_artifact_id(seed, prefix="fx")
#
#     rec = {
#         "artifact_id": artifact_id,
#         "topic_id": topic_id,
#         "section": section,
#         "created_by": created_by,
#         "created_at_ms": now_ms(),
#         "uri": uri or "",
#         "preview": (content_preview or "")[:400],
#         "intended_owner": intended_owner or ""
#     }
#
#     rec["task_id"] = os.getenv("TASK_ID","")
#     rec["seed"] = int(os.getenv("SEED","11"))
#     reg.setdefault(section, []).append(rec)
#     reg.setdefault("artifacts", []).append(rec)
#     _save(rid, reg)
#     return {"status": "ok", "artifact_id": artifact_id, "topic_id": topic_id, "section": section, "uri": uri or ""}

def bb_write(*, run_id: Optional[str],
             topic_id: str,
             section: str,
             content_preview: str,
             created_by: str,
             uri: str = "",
             intended_owner: str = "",
             state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    寫一筆到 blackboard（facts / datasets / citations / open_issues）
    回傳: {"status":"ok","artifact_id":..., "topic_id":..., "section":..., "uri":...}
    ＊已內建 emit_bb_write / note_tool_call（供 ETL）
    """
    t0 = now_ms()
    rid = _resolve_run_id(run_id)
    with BLACKBOARD_LOCK:
        reg = _load(rid)

        seed = f"{rid}|{topic_id}|{section}|{(content_preview or '')[:64]}|{time.time()}"
        artifact_id = _mk_artifact_id(seed, prefix="fx")

        rec = {
            "artifact_id": artifact_id,
            "topic_id": topic_id,
            "section": section,
            "created_by": created_by or os.environ.get("AGENT","SYS"),
            "created_at_ms": now_ms(),
            "uri": uri or "",
            "preview": (content_preview or "")[:400],
            "intended_owner": intended_owner or "",
            "task_id": os.getenv("TASK_ID",""),
            "seed": int(os.getenv("SEED","11")),
        }
        reg.setdefault(section, []).append(rec)
        reg.setdefault("artifacts", []).append(rec)
        _save(rid, reg)

    # === 事件打點（ETL 會吃）===
    try:
        emit_bb_write(
            agent=rec["created_by"],
            topic_id=topic_id,
            section=section,
            artifact_id=artifact_id,
            uri=rec["uri"],
            intended_owner=rec["intended_owner"],
            turn_index=(state or {}).get("turn_counter"),
            state=state
        )
        note_tool_call(
            agent=rec["created_by"],
            tool_name=f"bb_write:{section}",
            ok=True,
            latency_ms=now_ms()-t0,
            args_head=content_preview[:120],
            topic_id=topic_id,
            state=state,
            turn_index=(state or {}).get("turn_counter")
        )
    except Exception:
        pass

    return {"status": "ok", "artifact_id": artifact_id, "topic_id": topic_id, "section": section, "uri": rec["uri"]}

# def bb_read(*, run_id: Optional[str],
#             topic_id: Optional[str] = None,
#             section: str = "facts",
#             limit: int = 50) -> Dict[str, Any]:
#     """
#     讀 blackboard 的某個 section；可選擇 topic_id 過濾，回傳本次提供的 artifact_id 清單。
#     """
#     rid = _resolve_run_id(run_id)
#     reg = _load(rid)
#
#     items: List[Dict[str, Any]] = []
#     for it in reg.get(section, []):
#         if topic_id and it.get("topic_id") != topic_id:
#             continue
#         items.append(it)
#     items = list(reversed(items))[: int(limit or 50)]
#     served_ids = [it.get("artifact_id") for it in items if it.get("artifact_id")]
#
#     text = "\n".join([f"- [{it['artifact_id']}] {it.get('preview','')}" for it in items])
#     return {
#         "status": "ok",
#         "section": section,
#         "count": len(items),
#         "fact_ids_served": served_ids,
#         "text": text
#     }

def bb_read(*, run_id: Optional[str],
            topic_id: Optional[str] = None,
            section: str = "facts",
            limit: int = 50,
            agent: Optional[str] = None,
            state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    讀 blackboard 的某個 section；可選擇 topic_id 過濾，回傳本次提供的 artifact_id 清單。
    ＊已內建 emit_bb_read / note_tool_call（供 ETL）
    """
    t0 = now_ms()
    rid = _resolve_run_id(run_id)
    reg = _load(rid)

    items: List[Dict[str, Any]] = []
    for it in reg.get(section, []):
        if topic_id and it.get("topic_id") != topic_id:
            continue
        items.append(it)
    items = list(reversed(items))[: int(limit or 50)]
    served_ids = [it.get("artifact_id") for it in items if it.get("artifact_id")]

    # === 事件打點（逐筆 read），供 t_first_read / t_owner_read / reuse / orphan ===
    reader = agent or os.environ.get("AGENT") or "SYS"
    try:
        for fx in served_ids:
            emit_bb_read(
                agent=reader,
                topic_id=(topic_id or ""),
                section=section,
                fact_ids_served=[fx],
                turn_index=(state or {}).get("turn_counter"),
                state=state
            )
        note_tool_call(
            agent=reader,
            tool_name=f"bb_read:{section}",
            ok=True,
            latency_ms=now_ms()-t0,
            args_head=f"topic={topic_id or ''},limit={limit}",
            topic_id=(topic_id or ""),
            state=state,
            turn_index=(state or {}).get("turn_counter")
        )
    except Exception:
        pass

    text = "\n".join([f"- [{it['artifact_id']}] {it.get('preview','')}" for it in items])
    return {"status":"ok",
            "section":section,
            "count":len(items),
            "fact_ids_served":served_ids,
            "text":text}


# ========= dataset helpers（程式用） =========
# def bb_register_dataset_path(
#     run_id: Optional[str],
#     name: str,
#     path: str,
#     fmt: Optional[str] = None,
#     rows: Optional[int] = None,
#     columns: Optional[List[str]] = None,
#     meta: Optional[Dict[str, Any]] = None,
#     topic_id: str = "",
#     created_by: str = "DE"
# ) -> Dict[str, Any]:
#     """
#     直接將檔案（parquet/csv）註冊到 blackboard 的 datasets；同時建立 artifact 索引。
#     """
#     rid = _resolve_run_id(run_id)
#     reg = _load(rid)
#
#     ext = (os.path.splitext(path)[1] or "").lower()
#     fmt_inferred = "parquet" if ext == ".parquet" else "csv" if ext == ".csv" else "unknown"
#     fmt = fmt or fmt_inferred
#
#     now = now_ms()
#     dataset_id = f"ds_{uuid.uuid4().hex[:8]}"
#     # 也給 dataset 一個 artifact_id（讓 read 可以統一記錄）
#     artifact_id = _mk_artifact_id(f"{rid}|{topic_id}|datasets|{path}|{time.time()}", prefix="fx")
#
#     item = {
#         "id": dataset_id,
#         "artifact_id": artifact_id,
#         "name": name,
#         "ref": path,
#         "format": fmt,
#         "rows": rows,
#         "schema": columns,
#         "created_ms": now,
#         "agent": created_by,
#         "desc": (meta or {}).get("desc"),
#         "meta": meta or {},
#         "topic_id": topic_id,
#     }
#     reg["datasets"].append(item)
#
#     # 加進 artifacts 索引（與 bb_write 對齊）
#     reg["artifacts"].append({
#         "artifact_id": artifact_id,
#         "topic_id": topic_id,
#         "section": "datasets",
#         "created_by": created_by,
#         "created_at_ms": now,
#         "uri": path,
#         "preview": name or os.path.basename(path),
#         "intended_owner": (meta or {}).get("intended_owner", "")
#     })
#
#     _save(rid, reg)
#     return {"status": "ok", "dataset": item}

def bb_register_dataset_path(
    run_id: Optional[str],
    name: str,
    path: str,
    fmt: Optional[str] = None,
    rows: Optional[int] = None,
    columns: Optional[List[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
    topic_id: str = "",
    created_by: str = "DE",
    state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    直接將檔案（parquet/csv）註冊到 blackboard 的 datasets；同時建立 artifact 索引並 emit 事件。
    """
    rid = _resolve_run_id(run_id)
    ext = (os.path.splitext(path)[1] or "").lower()
    fmt_inferred = "parquet" if ext == ".parquet" else "csv" if ext == ".csv" else "unknown"
    fmt = fmt or fmt_inferred

    nowt = now_ms()
    dataset_id = f"ds_{uuid.uuid4().hex[:8]}"
    artifact_id = _mk_artifact_id(f"{rid}|{topic_id}|datasets|{path}|{time.time()}", prefix="fx")

    item = {
        "id": dataset_id,
        "artifact_id": artifact_id,
        "name": name,
        "ref": path,
        "format": fmt,
        "rows": rows,
        "schema": columns,
        "created_ms": nowt,
        "agent": created_by,
        "desc": (meta or {}).get("desc"),
        "meta": meta or {},
        "topic_id": topic_id,
    }
    with BLACKBOARD_LOCK:
        reg = _load(rid)
        reg.setdefault("datasets", []).append(item)

        reg.setdefault("artifacts", []).append({
            "artifact_id": artifact_id,
            "topic_id": topic_id,
            "section": "datasets",
            "created_by": created_by,
            "created_at_ms": nowt,
            "uri": path,
            "preview": name or os.path.basename(path),
            "intended_owner": (meta or {}).get("intended_owner", "")
        })
        _save(rid, reg)

    # === 事件打點（資料集寫入）===
    try:
        emit_bb_write(
            agent=created_by,
            topic_id=topic_id,
            section="datasets",
            artifact_id=artifact_id,
            uri=path,
            intended_owner=(meta or {}).get("intended_owner", ""),
            turn_index=(state or {}).get("turn_counter"),
            state=state
        )
        note_tool_call(
            agent=created_by,
            tool_name="bb_write:datasets",
            ok=True,
            latency_ms=0,
            args_head=name[:120],
            topic_id=topic_id,
            state=state,
            turn_index=(state or {}).get("turn_counter")
        )
    except Exception:
        pass

    return {"status": "ok", "dataset": item}

def bb_list_datasets_py(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rid = _resolve_run_id(run_id)
    return _load(rid).get("datasets", [])

def bb_latest_dataset_py(run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    rid = _resolve_run_id(run_id)
    ds = _load(rid).get("datasets", [])
    return ds[-1] if ds else None

def get_bb_snapshot(run_id: Optional[str] = None) -> Dict[str, Any]:
    rid = _resolve_run_id(run_id)
    return _load(rid)

# ========= LangChain tools（供 LLM 呼叫；回傳 JSON 字串） =========

@tool
def bb_register_dataset(
    ref: str,
    fmt: str = "parquet",
    rows: Optional[int] = None,
    columns: Optional[List[str]] = None,
    desc: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    """
    將產出的資料檔註冊到 blackboard.datasets；同時建立 artifact_id。
    回傳: {"status":"ok","dataset":{...}}
    """
    rid = _resolve_run_id(None)
    nowt = now_ms()
    dataset_id = f"ds_{uuid.uuid4().hex[:8]}"
    artifact_id = _mk_artifact_id(f"{rid}|datasets|{ref}|{time.time()}", prefix="fx")

    item = {
        "id": dataset_id,
        "artifact_id": artifact_id,
        "name": name or f"dataset_{nowt}",
        "ref": ref,
        "format": fmt,
        "rows": rows,
        "schema": columns,
        "created_ms": nowt,
        "agent": "DE",
        "desc": desc,
        "meta": {},
        "topic_id": "",
    }
    with BLACKBOARD_LOCK:
        reg = _load(rid)
        reg["datasets"].append(item)
        reg["artifacts"].append({
            "artifact_id": artifact_id,
            "topic_id": "",
            "section": "datasets",
            "created_by": "DE",
            "created_at_ms": nowt,
            "uri": ref,
            "preview": item["name"],
            "intended_owner": ""
        })
        _save(rid, reg)
    return json.dumps({"status": "ok", "dataset": item}, ensure_ascii=False)

@tool
def bb_list_datasets() -> str:
    """列出目前 RUN_ID 的所有 datasets。"""
    rid = _resolve_run_id(None)
    return json.dumps({"status": "ok", "datasets": _load(rid).get("datasets", [])}, ensure_ascii=False)

@tool
def bb_get_latest_dataset() -> str:
    """取得目前 RUN_ID 最新的 dataset。"""
    rid = _resolve_run_id(None)
    ds = _load(rid).get("datasets", [])
    if ds:
        return json.dumps({"status": "ok", "dataset": ds[-1]}, ensure_ascii=False)
    return json.dumps({"status": "empty"})

@tool
def bb_preview_dataset(ref: str, n: int = 5) -> str:
    """
    預覽 parquet/csv 的欄位與前 n 列。
    回傳: {"status":"ok","columns":[...],"rowcount":N,"rows":[...] } 或 {"status":"error","error": "..."}
    """
    try:
        if ref.lower().endswith(".parquet"):
            df = pd.read_parquet(ref)
        else:
            df = pd.read_csv(ref)
        prv = df.head(n)
        return json.dumps(
            {"status": "ok", "columns": list(df.columns), "rowcount": int(len(df)),
             "rows": prv.to_dict(orient="records")},
            ensure_ascii=False
        )
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

@tool
def bb_list_facts() -> str:
    """列出目前 RUN_ID 的 facts（工具）。"""
    rid = _resolve_run_id(None)
    return json.dumps({"status": "ok", "facts": _load(rid).get("facts", [])}, ensure_ascii=False)

@tool
def bb_get_latest_fact() -> str:
    """取得目前 RUN_ID 最新的 fact（工具）。"""
    rid = _resolve_run_id(None)
    fx = _load(rid).get("facts", [])
    if fx:
        return json.dumps({"status": "ok", "fact": fx[-1]}, ensure_ascii=False)
    return json.dumps({"status": "empty"})

@tool
def bb_dump_registry(n: int = 3) -> str:
    """
    除錯輔助：回傳各 section 的最後 n 筆與 registry 路徑。
    """
    rid = _resolve_run_id(None)
    reg = _load(rid)
    out = {
        "run_id": rid,
        "facts_tail": reg.get("facts", [])[-n:],
        "datasets_tail": reg.get("datasets", [])[-n:],
        "citations_tail": reg.get("citations", [])[-n:],
        "open_issues_tail": reg.get("open_issues", [])[-n:],
        "artifacts_tail": reg.get("artifacts", [])[-n:],
        "path": _bb_path(rid),
    }
    return json.dumps({"status": "ok", "snapshot": out}, ensure_ascii=False)

# ========= high-level write (programmatic) =========

def _dump_content_blob(run_id: Optional[str], artifact_id: str, content: Any) -> str:
    """把 content 落成 JSON 檔，回傳檔案路徑；供 write_to_blackboard 產生 uri。"""
    rid = _resolve_run_id(run_id)
    bb_dir = os.path.dirname(_bb_path(rid))
    os.makedirs(bb_dir, exist_ok=True)
    path = os.path.join(bb_dir, f"{artifact_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        # 即使內容無法序列化，也不讓主流程中斷
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(content))
    return path

# def write_to_blackboard(
#     *,
#     section: str,
#     summary: str = "",
#     content: Any = None,
#     state: Optional[Dict[str, Any]] = None,
#     topic_id: str = "",
#     owner: str = "",
#     created_by: str = ""
# ) -> Dict[str, Any]:
#     """
#     高階封裝：把 content 先存成 blob，再用 bb_write 記一筆（含 artifact_id/uri）。
#     - state 若提供，會同步鏡射一筆到 state['blackboard'][section]（不影響舊邏輯）
#     - created_by 若未指定，嘗試用環境變數 AGENT / 否則 'SYS'
#     """
#     rid = _resolve_run_id(None)
#     agent_name = created_by or os.environ.get("AGENT") or "SYS"
#
#     # 先用 bb_write 產生 artifact_id（但先不給 uri，取回 id 後再落 blob）
#     # 這裡用臨時 preview，待拿到 artifact_id 後再覆寫（可選）
#     tmp = bb_write(
#         run_id=rid,
#         topic_id=topic_id or "",
#         section=section,
#         content_preview=(summary or str(content)[:120]),
#         created_by=agent_name,
#         uri="",  # 先空著，下面會帶著 artifact_id 寫 blob 再覆寫
#         intended_owner=owner or "",
#         state=state
#     )
#     if tmp.get("status") != "ok":
#         return {"status": "error", "error": "bb_write failed"}
#
#     fxid = tmp["artifact_id"]
#     uri_path = _dump_content_blob(rid, fxid, content)
#
#     # 讀回 registry，覆寫該 artifact 的 uri 與 preview（保險起見）
#     reg = _load(rid)
#     for it in reg.get(section, []):
#         if it.get("artifact_id") == fxid:
#             it["uri"] = uri_path
#             if summary:
#                 it["preview"] = summary[:400]
#             break
#     for it in reg.get("artifacts", []):
#         if it.get("artifact_id") == fxid:
#             it["uri"] = uri_path
#             if summary:
#                 it["preview"] = summary[:400]
#             break
#     _save(rid, reg)
#
#     # 可選：鏡射到 state（讓當回合下游 agent 能看見）
#     if isinstance(state, dict):
#         shadow = {
#             "artifact_id": fxid, "topic_id": topic_id or "", "section": section,
#             "created_by": agent_name, "created_at_ms": now_ms(), "uri": uri_path,
#             "preview": (summary or str(content)[:120]), "intended_owner": owner or ""
#         }
#         state.setdefault("blackboard", {}).setdefault(section, []).append(shadow)
#
#     return {"status": "ok", "artifact_id": fxid, "uri": uri_path, "section": section, "topic_id": topic_id or ""}

def write_to_blackboard(
    *,
    section: str,
    summary: str = "",
    content: Any = None,
    state: Optional[Dict[str, Any]] = None,
    topic_id: str = "",
    owner: str = "",
    created_by: str = ""
) -> Dict[str, Any]:
    """
    高階封裝：把 content 先存成 blob，再用 bb_write 記一筆（含 artifact_id/uri）。
    - 會 mirror 到 state['blackboard'][section]（不影響舊邏輯）
    - 事件（bb_write）已在 bb_write 裡打點
    """
    rid = _resolve_run_id(None)
    agent_name = created_by or os.environ.get("AGENT") or "SYS"

    # 先註冊（會 emit_bb_write）
    tmp = bb_write(
        run_id=rid,
        topic_id=topic_id or "",
        section=section,
        content_preview=(summary or str(content)[:120]),
        created_by=agent_name,
        uri="",
        intended_owner=owner or "",
        state=state
    )
    if tmp.get("status") != "ok":
        return {"status": "error", "error": "bb_write failed"}

    fxid = tmp["artifact_id"]
    uri_path = _dump_content_blob(rid, fxid, content)

    # 覆寫該 artifact 的 uri / preview
    with BLACKBOARD_LOCK:
        reg = _load(rid)
        for it in reg.get(section, []):
            if it.get("artifact_id") == fxid:
                it["uri"] = uri_path
                if summary:
                    it["preview"] = summary[:400]
                break
        for it in reg.get("artifacts", []):
            if it.get("artifact_id") == fxid:
                it["uri"] = uri_path
                if summary:
                    it["preview"] = summary[:400]
                break
        _save(rid, reg)

    # 鏡射到 state（讓同回合可見）
    if isinstance(state, dict):
        shadow = {
            "artifact_id": fxid, "topic_id": topic_id or "", "section": section,
            "created_by": agent_name, "created_at_ms": now_ms(), "uri": uri_path,
            "preview": (summary or str(content)[:120]), "intended_owner": owner or ""
        }
        state.setdefault("blackboard", {}).setdefault(section, []).append(shadow)

    return {"status": "ok", "artifact_id": fxid, "uri": uri_path, "section": section, "topic_id": topic_id or ""}

@tool
def write_to_blackboard(section: str, summary: str = "", content: Any = None) -> str:
    """
    LangChain Tool 版本：給代理直接呼叫。
    只需傳 section/summary/content；topic/owner/created_by 由環境推斷。
    回傳 JSON: {"status":"ok","artifact_id":...,"uri":...}
    """
    try:
        out = write_to_blackboard(
            section=section,
            summary=summary,
            content=content,
            state=None,
            topic_id=os.environ.get("TOPIC_ID",""),
            owner=os.environ.get("OWNER",""),
            created_by=os.environ.get("AGENT","")
        )
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)


# ========= programmatic bulk append（可保留相容） =========

def bb_add_citations(run_id: Optional[str], citations: List[Dict[str, Any]]) -> None:
    """批次加入 citations（含去重），常用於程式內部。"""
    rid = _resolve_run_id(run_id)
    with BLACKBOARD_LOCK:
        reg = _load(rid)
        reg.setdefault("citations", [])
        seen = {(c.get("doc_id"), int(c.get("page", 0)), (c.get("quote") or "")) for c in reg["citations"]}
        for c in (citations or []):
            key = (c.get("doc_id"), int(c.get("page", 0)), (c.get("quote") or ""))
            if key not in seen:
                reg["citations"].append(c)
                seen.add(key)
        _save(rid, reg)

def bb_add_facts(
    run_id: Optional[str],
    facts: List[Any],
    agent: str = "unknown",
    source_tool: str = "unknown",
) -> None:
    """批次加入 facts，自動正規化為 provenance dict 格式。"""
    rid = _resolve_run_id(run_id)
    with BLACKBOARD_LOCK:
        reg = _load(rid)
        reg.setdefault("facts", [])
        for f in (facts or []):
            if isinstance(f, str):
                entry = _fact_entry(claim=f, agent=agent, source_tool=source_tool)
            elif isinstance(f, dict) and "claim" in f:
                entry = f
            elif isinstance(f, dict):
                claim = str(f.get("text") or f.get("content") or f)
                entry = _fact_entry(claim=claim, agent=agent, source_tool=source_tool)
            else:
                entry = _fact_entry(claim=str(f), agent=agent, source_tool=source_tool)
            reg["facts"].append(entry)
        _save(rid, reg)
