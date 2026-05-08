# runjson_to_events.py
# 批次版：掃描資料夾或 manifest，一次把多個 chat_*.json + *_stdout.txt 轉成事件表
import argparse, json, re, os, sys, hashlib, time, glob
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd

# ========= 基本工具 =========
NOW_MS = lambda: int(time.time() * 1000)

def _ms(ts: Optional[float | int]) -> Optional[int]:
    if ts is None:
        return None
    try:
        ts = int(ts)
        return ts if ts > 10**12 else int(ts * 1000)
    except Exception:
        return None

def _event_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _safe(d: dict, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict): return default
        cur = cur.get(k)
        if cur is None: return default
    return cur

# ========= 映射函式（和你單檔版一致，略有健壯性強化）=========
def map_tool_events(run_json: Dict[str, Any], run_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    tool_events = run_json.get("tool_events", []) or []
    for i, te in enumerate(tool_events):
        tool_name = te.get("tool", "")
        agent = te.get("agent", "")
        args = te.get("args") or {}
        raw_out = te.get("raw_output") or {}
        ok = te.get("ok", None)

        t0 = _ms(te.get("t_start_ms"))
        lat = te.get("latency_ms", None)
        t1 = (t0 + int(lat)) if (t0 is not None and isinstance(lat, (int, float))) else None

        event_type = f"tool_call:{tool_name}"
        artifact_id = raw_out.get("artifact_id")
        fact_ids = raw_out.get("fact_ids_served", [])
        bb_section = args.get("section", "")

        if artifact_id:
            event_type = "bb_write"
        elif fact_ids:
            event_type = "bb_read"

        addressed_to = ""
        channel = "private"
        topic_id = args.get("topic_id", "") or te.get("topic_id", "")

        if tool_name.startswith("delegate_to_"):
            addressed_to = tool_name.rsplit("_", 1)[-1].upper()
            channel = "team"

        head = ""
        try:
            head = (te.get("output_head") or "")[:200]
        except Exception:
            head = ""

        eid = te.get("id") or _event_id(f"{run_id}|tool|{i}|{tool_name}|{t0 or ''}")
        rows.append({
            "event_id": eid,
            "run_id": run_id,
            "turn_index": te.get("turn_index") or te.get("seq") or 0,
            "timestamp_ms": t0,
            "end_ms": t1,
            "latency_ms": int(lat) if isinstance(lat, (int, float)) else None,
            "agent": agent or "ToolCaller",
            "addressed_to": addressed_to,
            "channel": channel,
            "event_type": event_type,
            "tool_name": tool_name,
            "tool_success": ok,
            "topic_id": topic_id,
            "args_json": json.dumps(args, ensure_ascii=False),
            "bb_section": bb_section,
            "artifact_id": artifact_id or "",
            "fact_ids_served": json.dumps(fact_ids, ensure_ascii=False) if fact_ids else "[]",
            "content_head": head,
            "source": "tool_events"
        })
    return rows

def map_messages(run_json: Dict[str, Any], run_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    msgs = run_json.get("messages", []) or []
    turn_counter = run_json.get("turn_counter", None)

    for idx, m in enumerate(msgs):
        mtype = m.get("type")
        content = m.get("content")
        if not isinstance(content, str):
            try:
                content = json.dumps(content, ensure_ascii=False)[:500]
            except Exception:
                content = str(content)
        turn_index = turn_counter  # 沒逐則時間，用 run 內最後回合近似
        ts = None

        if mtype == "AIMessage":
            tcs = m.get("tool_calls") or []
            if tcs:
                for j, tc in enumerate(tcs):
                    name = tc.get("name", "")
                    args = tc.get("args") or {}
                    tool_call_id = tc.get("id") or _event_id(f"{run_id}|intent|{idx}|{j}|{name}")
                    rows.append({
                        "event_id": tool_call_id,
                        "run_id": run_id,
                        "turn_index": turn_index,
                        "timestamp_ms": ts,
                        "end_ms": None,
                        "latency_ms": None,
                        "agent": "Supervisor",
                        "addressed_to": name.rsplit("_", 1)[-1].upper() if name.startswith("delegate_to_") else "",
                        "channel": "team" if name.startswith("delegate_to_") else "private",
                        "event_type": "intent",
                        "tool_name": name,
                        "tool_success": None,
                        "topic_id": args.get("topic_id", ""),
                        "args_json": json.dumps(args, ensure_ascii=False),
                        "bb_section": "",
                        "artifact_id": "",
                        "fact_ids_served": "[]",
                        "content_head": (content or "")[:200],
                        "source": "messages.intent"
                    })
            else:
                rows.append({
                    "event_id": _event_id(f"{run_id}|ai|{idx}"),
                    "run_id": run_id,
                    "turn_index": turn_index,
                    "timestamp_ms": ts,
                    "end_ms": None,
                    "latency_ms": None,
                    "agent": "Supervisor",
                    "addressed_to": "",
                    "channel": "team",
                    "event_type": "say",
                    "tool_name": "",
                    "tool_success": None,
                    "topic_id": "",
                    "args_json": "{}",
                    "bb_section": "",
                    "artifact_id": "",
                    "fact_ids_served": "[]",
                    "content_head": (content or "")[:200],
                    "source": "messages.say"
                })

        elif mtype == "ToolMessage":
            name = m.get("name", "")
            tool_call_id = m.get("tool_call_id") or _event_id(f"{run_id}|toolres|{idx}|{name}")
            rows.append({
                "event_id": tool_call_id,
                "run_id": run_id,
                "turn_index": turn_index,
                "timestamp_ms": ts,
                "end_ms": None,
                "latency_ms": None,
                "agent": name.rsplit("_", 1)[-1].upper() if name.startswith("delegate_to_") else "Tool",
                "addressed_to": "Supervisor",
                "channel": "team",
                "event_type": "tool_result",
                "tool_name": name,
                "tool_success": None,
                "topic_id": "",
                "args_json": "{}",
                "bb_section": "",
                "artifact_id": "",
                "fact_ids_served": "[]",
                "content_head": (m.get("content") or "")[:200],
                "source": "messages.tool_result"
            })
        else:
            rows.append({
                "event_id": _event_id(f"{run_id}|{mtype}|{idx}"),
                "run_id": run_id,
                "turn_index": turn_index,
                "timestamp_ms": ts,
                "end_ms": None,
                "latency_ms": None,
                "agent": "User" if mtype == "HumanMessage" else (mtype or ""),
                "addressed_to": "Supervisor",
                "channel": "team",
                "event_type": "say",
                "tool_name": "",
                "tool_success": None,
                "topic_id": "",
                "args_json": "{}",
                "bb_section": "",
                "artifact_id": "",
                "fact_ids_served": "[]",
                "content_head": (content or "")[:200],
                "source": f"messages.{mtype}"
            })
    return rows

def map_stdout(stdout_path: Optional[str]) -> Dict[str, Any]:
    out = {"run_start_ms": None, "run_end_ms": None, "turn_boundaries": []}
    if not stdout_path or not os.path.exists(stdout_path):
        return out

    start_ms = None
    end_ms = None
    turns: List[Tuple[int, int]] = []
    TURN_RE = re.compile(r"STARTING TURN #(\d+)", re.I)
    END_RE = re.compile(r"JSON 状态已成功储存|JSON 狀態已成功儲存|JSON 状态已成功保存", re.I)

    with open(stdout_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if start_ms is None and ("MAS 互動模式" in line or "MAS 互动模式" in line or "MAS" in line):
                start_ms = NOW_MS()
            m = TURN_RE.search(line)
            if m:
                try:
                    t_idx = int(m.group(1))
                    turns.append((t_idx, NOW_MS()))
                except Exception:
                    pass
            if END_RE.search(line):
                end_ms = NOW_MS()

    out["run_start_ms"] = start_ms
    out["run_end_ms"] = end_ms
    out["turn_boundaries"] = turns
    return out

# ========= 正規化與輸出 =========
REQ_COLS = [
    "event_id","run_id","turn_index","timestamp_ms","end_ms","latency_ms",
    "agent","addressed_to","channel","event_type","tool_name","tool_success",
    "topic_id","args_json","bb_section","artifact_id","fact_ids_served",
    "content_head","source"
]

def normalize_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=REQ_COLS)
    df = pd.DataFrame(rows)
    for c in REQ_COLS:
        if c not in df.columns: df[c] = None
    df = df[REQ_COLS]
    df["_order"] = range(len(df))
    df = df.sort_values(["run_id","timestamp_ms","turn_index","_order"], na_position="last").drop(columns=["_order"])
    return df

def write_outputs(df: pd.DataFrame, out_dir: str, per_run: bool):
    os.makedirs(out_dir, exist_ok=True)
    # 全批
    all_parquet = os.path.join(out_dir, "events.parquet")
    all_csv = os.path.join(out_dir, "events.csv")
    df.to_parquet(all_parquet, index=False)
    df.to_csv(all_csv, index=False, encoding="utf-8-sig")
    # 逐 run（可選）
    if per_run:
        pr = os.path.join(out_dir, "per_run")
        os.makedirs(pr, exist_ok=True)
        for rid, g in df.groupby("run_id"):
            g.to_parquet(os.path.join(pr, f"{rid}.parquet"), index=False)
            g.to_csv(os.path.join(pr, f"{rid}.csv"), index=False, encoding="utf-8-sig")
    print(f"[OK] Wrote batch: {all_parquet} / {all_csv}")

# ========= 檔案來源蒐集與自動配對 =========
def _infer_run_id_from_json_path(path: str, j: Dict[str,Any]) -> str:
    rid = j.get("run_id") or j.get("session_id")
    if rid: return rid
    base = os.path.basename(path)
    m = re.search(r"chat_([0-9_]+_[0-9a-f]{8})", base)
    return m.group(1) if m else _event_id(base)

def discover_inputs(in_chat_dir: Optional[str], in_stdout_dir: Optional[str],
                    glob_chat: Optional[str], glob_stdout: Optional[str],
                    manifest: Optional[str]) -> List[Tuple[str, Optional[str]]]:
    pairs: List[Tuple[str, Optional[str]]] = []

    if manifest:
        df = pd.read_csv(manifest)
        for _, r in df.iterrows():
            pairs.append((str(r["run_json"]), str(r["stdout"]) if pd.notnull(r.get("stdout")) else None))
        return pairs

    chat_paths: List[str] = []
    if glob_chat:
        chat_paths = glob.glob(glob_chat, recursive=True)
    elif in_chat_dir:
        chat_paths = glob.glob(os.path.join(in_chat_dir, "**", "chat_*_turn_*_end.json"), recursive=True)
        chat_paths += glob.glob(os.path.join(in_chat_dir, "**", "chat_*_final_interrupt.json"), recursive=True)
    chat_paths = sorted(set([p for p in chat_paths if os.path.isfile(p)]))

    stdout_paths: List[str] = []
    if glob_stdout:
        stdout_paths = glob.glob(glob_stdout, recursive=True)
    elif in_stdout_dir:
        stdout_paths = glob.glob(os.path.join(in_stdout_dir, "**", "*stdout.txt"), recursive=True)
    stdout_paths = sorted(set([p for p in stdout_paths if os.path.isfile(p)]))

    # 建立索引：用檔名的前綴（時間戳 + 8 字元 hash）做近似配對
    # chat: chat_YYYYMMDD_HHMMSS_xxxxxxxx_..._turn_*.json
    # stdout: YYYYMMDD_HHMMSS_xxxxxxxx_stdout.txt（或相似）
    def _key_from_path(p: str) -> Optional[str]:
        b = os.path.basename(p)
        m = re.search(r"(\d{8}_\d{6}_[0-9a-f]{8})", b)
        return m.group(1) if m else None

    std_idx: Dict[str, str] = {}
    for sp in stdout_paths:
        k = _key_from_path(sp)
        if k: std_idx[k] = sp

    for cp in chat_paths:
        k = _key_from_path(cp)
        sp = std_idx.get(k)
        pairs.append((cp, sp))

    return pairs

# ========= 主流程 =========
def process_one(run_json_path: str, stdout_path: Optional[str]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    run_json = _read_json(run_json_path)
    run_id = _infer_run_id_from_json_path(run_json_path, run_json)

    rows = []
    rows += map_tool_events(run_json, run_id)
    rows += map_messages(run_json, run_id)
    df = normalize_df(rows)

    info = map_stdout(stdout_path)
    meta = {
        "run_id": run_id,
        "source_json": os.path.abspath(run_json_path),
        "source_stdout": os.path.abspath(stdout_path) if stdout_path else None,
        "run_start_ms": info.get("run_start_ms"),
        "run_end_ms": info.get("run_end_ms"),
        "turn_boundaries": info.get("turn_boundaries", []),
        "counts": {
            "events": int(len(df)),
            "bb_write": int((df["event_type"] == "bb_write").sum()),
            "bb_read": int((df["event_type"] == "bb_read").sum()),
            "intent": int((df["event_type"] == "intent").sum()),
        }
    }
    return df, meta

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in_chat_dir", default=None, help="掃描 chat_* JSON 的根資料夾（遞迴）")
    ap.add_argument("--in_stdout_dir", default=None, help="掃描 *_stdout.txt 的根資料夾（遞迴）")
    ap.add_argument("--glob_chat", default=None, help="自訂 chat JSON 的 glob（支援 **）")
    ap.add_argument("--glob_stdout", default=None, help="自訂 stdout 的 glob（支援 **）")
    ap.add_argument("--manifest", default=None, help="CSV：欄位 run_json,stdout")
    ap.add_argument("--out_dir", required=True, help="輸出資料夾")
    ap.add_argument("--per_run", action="store_true", help="同時輸出每個 run 的獨立檔案")
    args = ap.parse_args()

    pairs = discover_inputs(args.in_chat_dir, args.in_stdout_dir, args.glob_chat, args.glob_stdout, args.manifest)
    if not pairs:
        print("[WARN] 找不到任何輸入（檢查 --in_chat_dir / --glob_chat / --manifest）")
        sys.exit(0)

    os.makedirs(args.out_dir, exist_ok=True)
    all_rows: List[pd.DataFrame] = []
    metas: List[Dict[str, Any]] = []

    for i, (cp, sp) in enumerate(pairs, 1):
        try:
            df, meta = process_one(cp, sp)
            all_rows.append(df)
            metas.append(meta)

            if args.per_run:
                pr_dir = os.path.join(args.out_dir, "per_run")
                os.makedirs(pr_dir, exist_ok=True)
                # 檔名用 run_id
                rid = meta["run_id"]
                df.to_parquet(os.path.join(pr_dir, f"{rid}.parquet"), index=False)
                df.to_csv(os.path.join(pr_dir, f"{rid}.csv"), index=False, encoding="utf-8-sig")

            print(f"[{i}/{len(pairs)}] OK: {os.path.basename(cp)}  (stdout={'Y' if sp else 'N'})")
        except Exception as e:
            print(f"[{i}/{len(pairs)}] FAIL: {cp}  ({e})")

    if not all_rows:
        print("[WARN] 全部輸入都失敗，無輸出。")
        sys.exit(0)

    big = pd.concat(all_rows, ignore_index=True)
    write_outputs(big, args.out_dir, per_run=args.per_run)

    # 批次 meta
    meta_path = os.path.join(args.out_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"runs": metas}, f, ensure_ascii=False, indent=2)
    print(f"[OK] Wrote meta: {meta_path}")

    # 快速摘要
    print("\n=== Quick Summary ===")
    print(big.groupby(["agent","event_type"])["event_id"].count().reset_index().rename(columns={"event_id":"n"}).to_string(index=False))

if __name__ == "__main__":
    main()
