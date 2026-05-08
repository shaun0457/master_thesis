# agent_log_parser_template.py
# Usage:
#   python agent_log_parser_template.py --data_dir /path/to/logs
# Outputs:
#   - agent_events.csv
#   - agent_behaviors.csv
#   - agent_timeline_joined.csv
#   - chart_events_by_agent.png
#   - chart_delegations.png
#   - chart_behaviors.png

# agent_log_parser_template.py — drop-in 版
import os, re, json, glob
from datetime import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 這兩個來自你已更新的 metrics.py（含 topic 生成與 7 構念 proxies）
from metrics import attach_topic_columns, compute_all_proxies
import json as _json_for_dump


# ---------------------------
# 基本工具
# ---------------------------
def derive_run_id(path):
    m = re.search(r'(\d{8}_\d{6}_[0-9a-f]{8})', os.path.basename(path))
    return m.group(1) if m else None

def safe_json_load(p):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"__error__": str(e), "__path__": p}

# ---------------------------
# 欄位正規化（關鍵：保證 event/tool_call/bb_section/details/agent*/event_time_ms/ok 存在）
# ---------------------------
def _ensure_events_schema(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        cols = ["run_id","event","tool_call","bb_section","details","agent_role","agent","event_time_ms","ok","policy","source","event_time_idx"]
        return pd.DataFrame(columns=cols)

    df = df.copy()

    # event
    if "event" not in df.columns:
        if "tool" in df.columns:
            df["event"] = df["tool"].apply(lambda x: f"tool:{x}" if isinstance(x, str) and x else None)
        elif "type" in df.columns:
            df["event"] = df["type"]
        elif "name" in df.columns:
            df["event"] = df["name"]
        elif "kind" in df.columns:
            df["event"] = df["kind"]
        else:
            df["event"] = None

    # tool_call
    if "tool_call" not in df.columns:
        df["tool_call"] = df["tool"] if "tool" in df.columns else None

    # bb_section
    if "bb_section" not in df.columns:
        df["bb_section"] = df["section"] if "section" in df.columns else None

    # details 應為 dict；合併 args/section
    if "details" not in df.columns:
        df["details"] = None

    def _mk_details(row):
        d = row.get("details", None)
        if not isinstance(d, dict):
            d = {}
        args = row.get("args", None)
        if isinstance(args, dict):
            d.setdefault("args", args)
        sec = row.get("bb_section") or row.get("section")
        if sec and "section" not in d:
            d["section"] = sec
        return d

    try:
        df["details"] = df.apply(_mk_details, axis=1)
    except Exception:
        pass

    # agent_role / agent
    if "agent_role" not in df.columns:
        df["agent_role"] = df["agent"] if "agent" in df.columns else None
    if "agent" not in df.columns:
        df["agent"] = df["agent_role"] if "agent_role" in df.columns else None

    # event_time_ms
    if "event_time_ms" not in df.columns:
        for cand in ["t_start_ms","ts_ms","timestamp","ts","time_ms","created_ms","start_ms"]:
            if cand in df.columns:
                df["event_time_ms"] = pd.to_numeric(df[cand], errors="coerce")
                break
        else:
            df["event_time_ms"] = pd.NA
    else:
        df["event_time_ms"] = pd.to_numeric(df["event_time_ms"], errors="coerce")

    # ok 轉布林
    if "ok" not in df.columns:
        df["ok"] = None
    df["ok"] = df["ok"].map(lambda x: True if x is True or x == "True" else (False if x is False or x == "False" else None))

    # 這幾個欄位保底
    for col in ["policy","source","event_time_idx"]:
        if col not in df.columns:
            df[col] = None

    return df

def normalize_timecols(df):
    df = df.copy()
    df["time_ms"] = df.get("event_time_ms")
    df["time_order"] = df.get("event_time_idx")
    df["approx_time"] = df["time_ms"]
    df.loc[df["approx_time"].isna(), "approx_time"] = df["time_order"]
    return df

# ---------------------------
# 解析 JSON / TXT
# ---------------------------
def parse_json_events(p):
    j = safe_json_load(p)
    run_id = j.get("run_id") or derive_run_id(p)
    policy = j.get("policy")
    rows = []

    # messages → delegation + roles
    for idx, msg in enumerate(j.get("messages", [])):
        role = msg.get("type")
        pseudo_ts = idx
        for tc in msg.get("tool_calls", []) or []:
            rows.append({
                "run_id": run_id,
                "source": "json",
                "policy": policy,
                "event_time_idx": pseudo_ts,
                "event": "delegate" if str(tc.get("name","")).startswith("delegate") else "tool_call",
                "agent_role": role,
                "tool_call": tc.get("name"),
                "args_keys": ",".join(sorted(list((tc.get("args") or {}).keys()))),
                "details": (tc.get("args") or {})
            })
        rows.append({
            "run_id": run_id,
            "source": "json",
            "policy": policy,
            "event_time_idx": pseudo_ts,
            "event": "message",
            "agent_role": role,
            "tool_call": None,
            "args_keys": None,
            "details": {"content_len": len(msg.get("content","") or "")}
        })

    # tool_events → tools / BB / SQL / etc.
    for ev in j.get("tool_events", []):
        t = ev.get("t_start_ms")
        ts = ev.get("ts")
        event_time = None
        if isinstance(t, (int, float)):
            event_time = int(t)
        elif ts:
            try:
                event_time = int(datetime.fromisoformat(ts).timestamp() * 1000)
            except Exception:
                event_time = None
        tool = ev.get("tool")
        agent = ev.get("agent", None)
        section = ev.get("section", None)
        ok = ev.get("ok")
        args = ev.get("args", {})
        rows.append({
            "run_id": run_id,
            "source": "json",
            "policy": policy,
            "event_time_ms": event_time,
            "event_time_idx": None,
            "event": f"tool:{tool}",
            "agent_role": agent,
            "tool_call": tool,
            "args_keys": ",".join(sorted(args.keys())) if isinstance(args, dict) else None,
            "ok": ok,
            "bb_section": section,
            "details": ev
        })
    return rows

def parse_txt_behaviors(p):
    run_id = derive_run_id(p)
    rows = []
    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
        for i, line in enumerate(f):
            s = line.strip()
            if not s:
                continue
            pseudo_ts = i
            label = None
            if "finished with no extractable summary" in s:
                label = "no_extract"
            elif re.search(r'\bKeyError\b', s):
                label = "KeyError"
            elif "write_to_blackboard" in s and re.search(r'"status"\s*:\s*"error"', s):
                label = "bb_error"
            elif "Current policy is 'free'" in s:
                label = "policy_free"
            elif s.startswith("[Node] >>>"):
                label = "node_enter"
            elif s.startswith("[Edge]"):
                label = "edge_event"
            elif ">>> Router" in s or s.startswith("[Router]"):
                label = "router_event"
            elif "Request to delegate" in s or "delegate_to_" in s:
                label = "delegate_event"
            elif re.search(r'\bException\b', s):
                label = "Exception"
            rows.append({
                "run_id": run_id,
                "source": "txt",
                "event_time_idx": pseudo_ts,
                "event": label or "log_line",
                "raw": s
            })
    return rows

# ---------------------------
# 主流程
# ---------------------------
def main(data_dir="."):
    # 讀檔
    json_paths = sorted(glob.glob(os.path.join(data_dir, "chat_*_turn_1_end.json")))
    txt_paths  = sorted(glob.glob(os.path.join(data_dir, "*_stdout.txt")))
    json_rows, txt_rows = [], []
    for p in json_paths:
        json_rows.extend(parse_json_events(p))
    for p in txt_paths:
        txt_rows.extend(parse_txt_behaviors(p))

    # DataFrame
    events_df    = pd.DataFrame(json_rows)
    behaviors_df = pd.DataFrame(txt_rows)

    # 先做欄位正規化，避免 KeyError（尤其是 event 欄）
    events_df = _ensure_events_schema(events_df)

    # 先補 topic_id（同題鏈接）
    try:
        events_df = attach_topic_columns(events_df)
    except Exception as _e:
        print(f"[WARN] attach_topic_columns 失敗：{type(_e).__name__}: {_e}")

    # 計算 7 個構念的 proxies
    try:
        if behaviors_df is None or behaviors_df.empty:
            behaviors_df = pd.DataFrame([])
        proxies = compute_all_proxies(events_df, behaviors_df)
    except Exception as _e:
        print(f"[WARN] compute_all_proxies 失敗：{type(_e).__name__}: {_e}")
        proxies = {}

    # 時序欄位
    events_df_n    = normalize_timecols(events_df)
    behaviors_df_n = normalize_timecols(behaviors_df)

    # timeline 需要的欄位保底
    for col in ["run_id","policy","approx_time","event","agent_role","tool_call","bb_section","source"]:
        if col not in events_df_n.columns:
            events_df_n[col] = np.nan
    for col in ["run_id","approx_time","event","source"]:
        if col not in behaviors_df_n.columns:
            behaviors_df_n[col] = np.nan
    behaviors_df_n["source"] = behaviors_df_n["source"].fillna("txt")

    # 合併時間線
    timeline_df = pd.concat([
        events_df_n.assign(kind="event")[["run_id","policy","approx_time","event","agent_role","tool_call","bb_section","source"]],
        behaviors_df_n.assign(kind="behavior")[["run_id","approx_time","event","source"]].assign(agent_role=np.nan, tool_call=np.nan, bb_section=np.nan)
    ], ignore_index=True).sort_values(["run_id","approx_time"])

    # 輸出 CSV
    events_csv   = os.path.join(data_dir, "agent_events.csv")
    behaviors_csv= os.path.join(data_dir, "agent_behaviors.csv")
    timeline_csv = os.path.join(data_dir, "agent_timeline_joined.csv")
    events_df.to_csv(events_csv, index=False)
    behaviors_df.to_csv(behaviors_csv, index=False)
    timeline_df.to_csv(timeline_csv, index=False)

    # 另外輸出含 topic 的事件表與 proxies.json
    events_with_topics_csv = os.path.join(data_dir, "agent_events_with_topics.csv")
    events_df.to_csv(events_with_topics_csv, index=False)
    proxies_json = os.path.join(data_dir, "proxies.json")
    with open(proxies_json, "w", encoding="utf-8") as f:
        _json_for_dump.dump(proxies, f, ensure_ascii=False, indent=2)

    print(f"[OK] events → {events_csv}")
    print(f"[OK] behaviors → {behaviors_csv}")
    print(f"[OK] timeline → {timeline_csv}")
    print(f"[OK] topics → {events_with_topics_csv}")
    print(f"[OK] proxies → {proxies_json}")

    # 簡單圖表（有資料才畫）
    try:
        if not events_df.empty:
            plt.figure()
            events_df.groupby("agent_role")["event"].count().sort_values(ascending=False).plot(kind="bar")
            plt.title("Event count by agent_role (JSON)")
            plt.xlabel("agent_role"); plt.ylabel("count"); plt.tight_layout()
            plt.savefig(os.path.join(data_dir, "chart_events_by_agent.png")); plt.close()

            plt.figure()
            if "delegate" in events_df["event"].unique():
                events_df[events_df["event"]=="delegate"]["tool_call"].value_counts().plot(kind="bar")
            else:
                # 若沒有 delegate 事件，就畫 tool_call top-N
                events_df["tool_call"].value_counts().nlargest(10).plot(kind="bar")
            plt.title("Delegation / Tool_call frequency (JSON)")
            plt.xlabel("tool_call"); plt.ylabel("count"); plt.tight_layout()
            plt.savefig(os.path.join(data_dir, "chart_delegations.png")); plt.close()

        if not behaviors_df.empty:
            plt.figure()
            behaviors_df["event"].value_counts().sort_values(ascending=False).plot(kind="bar")
            plt.title("Behavior label frequency (TXT)")
            plt.xlabel("behavior"); plt.ylabel("count"); plt.tight_layout()
            plt.savefig(os.path.join(data_dir, "chart_behaviors.png")); plt.close()
    except Exception as _e:
        print(f"[WARN] 畫圖失敗：{type(_e).__name__}: {_e}")

# ---------------------------
# 入口
# ---------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", default=".")
    args = parser.parse_args()
    main(args.data_dir)
