# metrics.py (兼容 ME 和 DS 實驗的最終版)
import time, json, re, hashlib
from typing import Optional, Dict, Any, List
import pandas as pd, numpy as np, networkx as nx, math, re, datetime as dt


# --- 時間工具 ---
def now_ms() -> int:
    return int(time.time() * 1000)


# --- 指標容器初始化 ---
def _ensure_metrics(state_or_obj: dict) -> dict:
    """確保 state 中存在 metrics 字典並返回，同時設定所有可能的預設值。"""
    m = state_or_obj.setdefault("metrics", {})
    if "t_start_ms" not in m: m["t_start_ms"] = now_ms()

    # 通用指標
    m.setdefault("tool_calls_total", 0)
    m.setdefault("ds_verdict", None)
    m.setdefault("ds_reason", None)
    m.setdefault("duration_ms", None)

    # ME 實驗專用指標
    m.setdefault("me_research_path_ok", 0)
    m.setdefault("me_synthesis_tool_used", 0)
    m.setdefault("me_answer_is_give_up", 0)
    m.setdefault("me_tool_limit_reached", 0)
    m.setdefault("me_final_answer_source", "Not Found")
    m.setdefault("me_hits_collected", 0)
    m.setdefault("me_citation_coverage", 0.0)
    m.setdefault("me_claims_count", 0)
    m.setdefault("me_uncited_claims", 0)

    # DS 實驗專用指標
    m.setdefault("ds_model_attempt_rate", 0.0)
    m.setdefault("ds_insight_depth_score", 0)
    m.setdefault("ds_repro_completeness", 0.0)

    return m


def init_metrics(state: dict, schema_snapshot: Optional[Dict[str, Any]] = None):
    """初始化一個新的實驗運行的 metrics 容器。"""
    m = _ensure_metrics(state)
    m["t_start_ms"] = now_ms()
    state.setdefault("tool_events", [])
    state.setdefault("hits", [])  # 確保 hits 列表存在
    if schema_snapshot is not None:
        m["schema_snapshot"] = schema_snapshot


def note_tool_event(state: dict, *, tool_name: str, args: dict, started_ms: int, latency_ms: int, raw_output: str):
    """記錄一次工具調用事件。"""
    m = _ensure_metrics(state)
    m["tool_calls_total"] += 1
    m.setdefault("me_tool_counts", {})[tool_name] = m.get("me_tool_counts", {}).get(tool_name, 0) + 1
    state.setdefault("tool_events", []).append({
        "t_start_ms": started_ms,
        "tool": tool_name,
        "args": args,
        "latency_ms": latency_ms,
        "output_head": (raw_output or "")[:500],
    })


# --- ME 實驗專用：引用覆蓋率計算 ---
CITE_RE = re.compile(r"\[(?P<doc>.+?\.(?:pdf|md|mdx))\s+p\.(?P<page>\d+)\]", re.I)
_BULLET_RE = re.compile(r"^\s*(?:[-*•\u2022]|\d+\.)\s+")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_TABLE_RE = re.compile(r"^\s*\|")
_CODE_FENCE = re.compile(r"^\s*```")
_SENT_BOUNDARY_RE = re.compile(r"(?<=[。．.!！？?])(?:\s+|$)")


def _split_sentences_for_metrics(text: str):
    """一個更穩健的句子切分器，能處理 Markdown 和程式碼。"""
    if not isinstance(text, str) or not text.strip(): return []
    lines = text.strip().splitlines()
    in_code = False
    sents = []
    for ln in lines:
        if _CODE_FENCE.match(ln):
            in_code = not in_code
            continue
        if in_code or not ln.strip() or re.match(r"^\s*(來源|参考|References|Sources)\s*[:：]", ln, flags=re.I):
            continue
        if _HEADING_RE.match(ln) or _TABLE_RE.match(ln) or _BULLET_RE.match(ln):
            sents.append(ln.strip());
            continue
        parts = _SENT_BOUNDARY_RE.split(ln)
        sents.extend(p for p in (p.strip() for p in parts) if p)
    return sents


def update_me_citation_metrics(state: dict, answer_text: str):
    """計算並更新 ME 代理人最終答案的引用覆蓋率。"""
    m = _ensure_metrics(state)
    sents = _split_sentences_for_metrics(answer_text)
    if not sents:
        m["me_citation_coverage"] = 0.0
        m["me_claims_count"] = 0
        m["me_uncited_claims"] = 0
        return

    covered = sum(1 for s in sents if CITE_RE.search(s) or s.strip().endswith("]"))
    total = len(sents)

    m["me_citation_coverage"] = round(covered / total, 3) if total > 0 else 0.0
    m["me_claims_count"] = total
    m["me_uncited_claims"] = total - covered


# --- 實驗收尾與評分 ---
def finalize_metrics(state: dict, ds_verdict: str, ds_reason: Optional[str] = None,
                     final_answer_obj: Optional[Dict] = None):
    """
    為實驗運行打上最終的 verdict 和分數，能夠智慧地區分 ME 和 DS 實驗。
    """
    m = _ensure_metrics(state)
    m["ds_reason"] = ds_reason
    m["duration_ms"] = now_ms() - m["t_start_ms"]

    # 判斷是 ME 還是 DS 實驗
    is_ds_experiment = any(ev.get("tool") == "execute_python_code" for ev in state.get("tool_events", []))

    if is_ds_experiment:
        # --- DS 實驗評分邏輯 ---
        if final_answer_obj:  # 只要成功解析出 JSON，就視為成功
            final_verdict = "SUCCESS"
            # 計算 DS 專屬指標
            m["ds_model_attempt_rate"] = 1.0 if 'sklearn' in ds_reason or 'model_details' in final_answer_obj else 0.0
            depth = 0
            if final_answer_obj.get("summary", {}).get("key_findings") or final_answer_obj.get("insights"): depth = 1
            if final_answer_obj.get("figures_generated") or final_answer_obj.get("figures"): depth = 2
            if final_answer_obj.get("model_details"): depth = 3
            if final_answer_obj.get("model_details", {}).get("feature_importances"): depth = 4
            m["ds_insight_depth_score"] = depth
            repro = final_answer_obj.get("reproducibility", {})
            repro_score = 0
            if repro.get("code_executed") and repro["code_executed"]: repro_score += 0.5
            if repro.get("seed"): repro_score += 0.5
            m["ds_repro_completeness"] = repro_score
        else:
            final_verdict = "FAILURE"
    else:
        # --- ME 實驗評分邏輯 ---
        cov = float(m.get("me_citation_coverage", 0.0))
        if cov > 0.3:
            final_verdict = "SUCCESS"
        elif cov > 0:
            final_verdict = "PARTIAL_SUCCESS"
        else:
            final_verdict = "FAILURE"

    m["ds_verdict"] = final_verdict

_XVAR_PAT = re.compile(r'\b(?:xmeas|xmv|x\d+meas)[_\s]*([0-9]{1,3})\b', re.IGNORECASE)
_MINUTE_PAT = re.compile(r'\b(1\s*min|1[-_\s]?minute|60\s*sec)\b', re.IGNORECASE)
_HOUR_PAT = re.compile(r'\b(48\s*h(ours)?|2\s*days)\b', re.IGNORECASE)

def _norm_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r'[\s]+', ' ', s).strip()
    return s

def _extract_seed_from_details(d: dict) -> str:
    if not isinstance(d, dict):
        return ""
    args = d.get("args") if isinstance(d.get("args"), dict) else d
    for k in ["task", "question", "topic"]:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v
    for k in ["query", "sql"]:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v
    v = args.get("summary")
    if isinstance(v, str) and v.strip():
        return v
    for k in ["task","question","topic","query","sql","summary","text"]:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""

def _extract_tokens(seed: str) -> dict:
    tok = {}
    if not seed:
        return tok
    vars_found = []
    for m in _XVAR_PAT.finditer(seed):
        varnum = m.group(1)
        whole = m.group(0).lower().replace(' ', '')
        if 'xmv' in whole:
            vars_found.append(f"xmv_{varnum}")
        else:
            vars_found.append(f"xmeas_{varnum}")
    if vars_found:
        tok["vars"] = sorted(set(vars_found))
    if _HOUR_PAT.search(seed):
        tok["win"] = "48h"
    if _MINUTE_PAT.search(seed):
        tok["sample"] = "1min"
    return tok

def make_topic_key(seed: str, fallback: str = "") -> str:
    seed_n = _norm_text(seed or "")
    t = _extract_tokens(seed_n)
    parts = []
    if "vars" in t: parts.append("|".join(t["vars"]))
    if "win" in t: parts.append(t["win"])
    if "sample" in t: parts.append(t["sample"])
    if not parts:
        if seed_n:
            parts = [seed_n[:80]]
        elif fallback:
            parts = [_norm_text(fallback)[:80]]
        else:
            parts = ["(general)"]
    return "|".join(parts)

def make_topic_id(topic_key: str) -> str:
    return f"t_{hashlib.sha1(topic_key.encode('utf-8')).hexdigest()[:10]}"

def attach_topic_columns(events_df: pd.DataFrame) -> pd.DataFrame:
    df = events_df.copy()
    def _row_topic_key(row):
        d = row.get("details", {})
        seed = _extract_seed_from_details(d) if isinstance(d, dict) else ""
        fallback = ""
        if isinstance(row.get("bb_section"), str) and row.get("bb_section"):
            fallback = row["bb_section"]
        if not fallback and isinstance(row.get("tool_call"), str):
            fallback = row["tool_call"]
        return make_topic_key(seed, fallback=fallback)
    df["topic_key"] = df.apply(_row_topic_key, axis=1)
    df["topic_id"] = df["topic_key"].map(make_topic_id)
    return df


# --- 可選：TF-IDF 相似，若沒裝 sklearn 就回落到 Jaccard ---
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_SK = True
except Exception:
    _HAS_SK = False

def _cosine_sim(a: str, b: str) -> float:
    a = (a or "").strip(); b = (b or "").strip()
    if not a or not b: return 0.0
    if _HAS_SK:
        vec = TfidfVectorizer(min_df=1).fit([a,b])
        X = vec.transform([a,b])
        return float(cosine_similarity(X[0], X[1])[0,0])
    # Jaccard fallback
    sa, sb = set(re.findall(r"[a-zA-Z0-9_]+", a.lower())), set(re.findall(r"[a-zA-Z0-9_]+", b.lower()))
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)

def _gini(x):
    x = np.asarray(list(x), dtype=float)
    if np.allclose(x.sum(), 0): return 0.0
    x = np.sort(x)
    n = x.size
    return (2*np.sum((np.arange(1, n+1))*x)/(n*x.sum())) - (n+1)/n

def _freeman_centralization(G: nx.DiGraph):
    # Freeman out-degree centralization on directed graph
    degs = np.array([G.out_degree(n) for n in G.nodes()], dtype=float)
    max_deg = degs.max() if degs.size else 0.0
    num = np.sum(max_deg - degs)
    # 最大可能值（星狀）= (n-1)*(n-2) for directed out-degree? 使用無向近似歸一化：上界=(n-1)*(n-2)
    n = G.number_of_nodes()
    denom = (n-1)*(n-2) if n>=3 else 1.0
    return float(num/denom) if denom>0 else 0.0

def _first(s):
    return next(iter(s), None)

def compute_leadership(events_df: pd.DataFrame):
    # 建立委派圖：邊 from=by_agent → to_agent，權重=次數
    # 來源：event=='delegate'（messages.tool_calls），以及 tool=request_delegate 的 tool_events
    df = events_df.copy()
    edges = []
    for _, r in df.iterrows():
        ev = r.get("event")
        tc = str(r.get("tool_call") or "")
        agent = r.get("agent_role") or r.get("agent")
        # delegate_to_* from 'agent_role' (Supervisor/Router) to target agent (from tool_call name)
        if ev == "delegate" and tc.startswith("delegate_to_"):
            to = tc[len("delegate_to_"):].upper()
            edges.append(("Supervisor", to))
        # request_delegate 是由某 agent 呼叫，希望轉派到另一 agent
        if isinstance(tc, str) and tc == "request_delegate":
            d = r.get("details") or {}
            args = d.get("args") or {}
            to = str(args.get("to","")).upper() or "UNK"
            edges.append((agent or "UNK", to))
    G = nx.DiGraph()
    for u,v in edges:
        G.add_edge(u,v, weight=G.get_edge_data(u,v,{}).get("weight",0)+1)
    freeman = _freeman_centralization(G)
    degs = {n: (G.out_degree(n), G.in_degree(n)) for n in G.nodes()}
    return {"freeman_centralization": freeman, "deg": degs}

def compute_knowledge_sharing(events_df: pd.DataFrame):
    # write→read 延遲、被他人讀取比率
    df = events_df.copy()
    if "event" not in df.columns:
        return {"write_read_delay_ms_mean": None, "read_by_others_ratio": None}
    if "tool_call" not in df.columns:
        df["tool_call"] = None
    if "bb_section" not in df.columns:
        df["bb_section"] = None
    # 抓 datasets 寫入
    try:
        writes = df[
            (df["event"].astype(str).str.startswith("tool:")) &
            (df["tool_call"]=="write_to_blackboard") &
            (df["bb_section"]=="datasets")
        ].copy()
    except Exception:
        return {"write_read_delay_ms_mean": None, "read_by_others_ratio": None}

    # 時間欄位
    tcol = "event_time_ms" if "event_time_ms" in df.columns else None
    if tcol is None:
        df["t"] = pd.NA
        writes["t"] = pd.NA
    else:
        df["t"] = pd.to_numeric(df[tcol], errors="coerce")
        writes["t"] = pd.to_numeric(writes[tcol], errors="coerce")

    reads = df[(df["event"].astype(str).str.startswith("tool:")) & (df["tool_call"]=="read_blackboard")].copy()
    reads["t"] = pd.to_numeric(reads.get(tcol), errors="coerce") if tcol else pd.NA

    delays, hit = [], 0
    for _, w in writes.iterrows():
        w_t = w.get("t")
        w_agent = w.get("agent_role") or w.get("agent")
        cand = reads.copy()
        if w_t == w_t:  # not NaN
            cand = cand[cand["t"] > w_t]
        # 非作者 read
        cand = cand[(cand.get("agent_role")!=w_agent) & (cand.get("agent")!=w_agent)]
        if len(cand):
            first = cand.sort_values("t").iloc[0]
            if (first.get("t") == first.get("t")) and (w_t == w_t):
                delays.append(float(first["t"]) - float(w_t))
            hit += 1

    delay_ms = float(np.mean(delays)) if delays else None
    ratio = hit / len(writes) if len(writes) else None
    return {"write_read_delay_ms_mean": delay_ms, "read_by_others_ratio": ratio}

def compute_coord_eff(events_df: pd.DataFrame):
    # 決策延遲：delegate 後到第一次 ok 的關鍵工具
    df = events_df.copy()
    df["t"] = pd.to_numeric(df.get("event_time_ms") or df.get("approx_time"))
    delegates = df[df["event"]=="delegate"].sort_values(["run_id","t"])
    tools_ok = df[(df["event"].str.startswith("tool:")) & (df.get("ok").astype(str)=="True")].copy()
    tools_ok = tools_ok.sort_values(["run_id","t"])
    deltas = []
    for _, d in delegates.iterrows():
        after = tools_ok[(tools_ok["run_id"]==d["run_id"]) & (tools_ok["t"]>d["t"])]
        if len(after):
            first = after.iloc[0]
            deltas.append(first["t"] - d["t"])
    path_len = None  # 需要 task_id 或 topic_id 較準確；可先用工具步數近似
    return {"decision_delay_ms_mean": float(np.mean(deltas)) if deltas else None,
            "approx_path_len": path_len}

def compute_team_learning(events_df: pd.DataFrame, behaviors_df: pd.DataFrame):
    # 同 topic 內：錯誤→成功的轉換率；反饋循環數
    df = events_df.copy()
    if "topic_id" not in df.columns:
        # 若你已使用 attach_topic_columns，這欄就會存在；否則先全部給同一題示意
        df["topic_id"] = "t_all"
    df["t"] = pd.to_numeric(df.get("event_time_ms") or df.get("approx_time"))
    df = df.sort_values(["run_id","topic_id","t"])
    conv = []
    loops = 0
    for (run, topic), g in df.groupby(["run_id","topic_id"]):
        flags = (g["event"].str.startswith("tool:")) & (g.get("ok").isin([True, "True"]))
        ok_positions = np.where(flags.values)[0]
        if len(ok_positions):
            first_ok = ok_positions[0]
            had_err_before = any((g["event"].str.startswith("tool:")) & (~g.get("ok").isin([True,"True"])) & (np.arange(len(g))<first_ok))
            conv.append(1.0 if had_err_before else 0.0)
        # 粗略回路：錯誤→ok→錯誤→ok 的次數
        seq = (g.get("ok").astype(str)=="True").tolist()
        for i in range(1, len(seq)):
            if seq[i] and not seq[i-1]: loops += 1
    rate = float(np.mean(conv)) if conv else None
    return {"cross_round_correction_rate": rate, "feedback_loops": loops}

def compute_goal_alignment(events_df: pd.DataFrame):
    # 初始任務 vs 後續報告/summary 的語意相似
    df = events_df.copy()
    q = None
    # 找第一個 delegate 的 question/task
    for _, r in df[df["event"]=="delegate"].iterrows():
        d = r.get("details") or {}
        a = d.get("args") or {}
        q = a.get("question") or a.get("task")
        if q: break
    # 找後續黑板 facts 的 summary 或最終 message
    summaries = []
    for _, r in df.iterrows():
        if r.get("bb_section")=="facts":
            d = (r.get("details") or {})
            a = d.get("args") or {}
            s = a.get("summary") or d.get("summary")
            if isinstance(s, str) and s.strip():
                summaries.append(s)
    tau = _cosine_sim(q or "", summaries[-1] if summaries else "")
    return {"goal_alignment_tau": tau, "has_summary": bool(summaries)}

def compute_conflict_handling(events_df: pd.DataFrame):
    # 連續 facts/plan 文本的差異 → 收斂時間
    df = events_df.copy()
    seq = []
    for _, r in df.iterrows():
        if r.get("bb_section") in ("facts","open_issues"):
            d = (r.get("details") or {})
            a = d.get("args") or {}
            s = a.get("summary") or d.get("summary")
            t = r.get("event_time_ms") or r.get("approx_time")
            if s: seq.append((t, s))
    if len(seq) < 2: return {"diverge_to_converge_turns": None, "diverge_to_converge_ms": None}
    seq = sorted(seq, key=lambda x: (x[0] is None, x[0]))
    base = seq[0][1]
    diverged_at, converged_at = None, None
    for i in range(1, len(seq)):
        sim = _cosine_sim(base, seq[i][1])
        if diverged_at is None and sim < 0.5:
            diverged_at = i
        if diverged_at is not None and sim >= 0.7:
            converged_at = i; break
    if diverged_at is None or converged_at is None:
        return {"diverge_to_converge_turns": None, "diverge_to_converge_ms": None}
    t0, t1 = seq[diverged_at][0], seq[converged_at][0]
    return {"diverge_to_converge_turns": int(converged_at - diverged_at),
            "diverge_to_converge_ms": float((t1 or 0) - (t0 or 0))}

def compute_workload_balance(events_df: pd.DataFrame):
    df = events_df.copy()
    by = df.groupby("agent_role")["event"].count()
    gini = _gini(by.values) if len(by)>0 else None
    H = -np.sum((by/by.sum()) * np.log((by/by.sum())+1e-12)) if by.sum()>0 else None
    return {"gini_by_agent": float(gini) if gini is not None else None,
            "entropy_by_agent": float(H) if H is not None else None,
            "counts": by.to_dict()}

def compute_all_proxies(events_df, behaviors_df):
    out = {}
    out["leadership"] = compute_leadership(events_df)
    out["knowledge_sharing"] = compute_knowledge_sharing(events_df)
    out["coord_eff"] = compute_coord_eff(events_df)
    out["team_learning"] = compute_team_learning(events_df, behaviors_df)
    out["goal_alignment"] = compute_goal_alignment(events_df)
    out["conflict"] = compute_conflict_handling(events_df)
    out["workload"] = compute_workload_balance(events_df)
    return out