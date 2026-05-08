# compute_proxies.py
# 讀 events.parquet → 輸出 run_metrics.parquet / 三張主圖（C/Gini/H；read-latency；reuse/orphan）
import argparse, os, json, ast
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ========== 小工具 ==========
def gini(x: np.ndarray) -> float:
    """Gini 不均衡係數。x>=0。"""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    x = x[x >= 0]
    if x.size == 0:
        return 0.0
    if x.sum() == 0:
        return 0.0
    x_sorted = np.sort(x)
    n = x_sorted.size
    cum = np.cumsum(x_sorted)
    g = (n + 1 - 2 * (cum.sum() / cum[-1]) ) / n
    return float(g)

def freeman_centralization_out(edges_df: pd.DataFrame) -> float:
    """
    Freeman out-degree centralization（簡化版）。
    edges_df 需有欄位: ['agent','addressed_to','w']；w 為權重（次數）。
    """
    if edges_df.empty:
        return 0.0
    nodes = pd.unique(edges_df[['agent','addressed_to']].values.ravel('K'))
    out_deg = edges_df.groupby('agent')['w'].sum().reindex(nodes, fill_value=0)
    n = len(nodes)
    if n <= 2:
        return 0.0
    max_k = out_deg.max()
    num = float((max_k - out_deg).sum())
    den = float((n - 1) * (n - 2))  # 有向 out-degree 的常見規模化近似
    return float(num / den) if den > 0 else 0.0

def handoff_entropy(edges_df: pd.DataFrame) -> float:
    """
    handoff 熵：對每個發出者 agent 的出邊分佈計 Entropy，對全體以出度加權平均；
    再用最大可能值 log(|V|-1) 規模化到 [0,1]。
    """
    if edges_df.empty:
        return 0.0
    df = edges_df.copy()
    # 每個 agent 的目的地分佈
    grp = df.groupby(['agent','addressed_to'])['w'].sum().reset_index()
    totals = grp.groupby('agent')['w'].sum().rename('tot')
    grp = grp.merge(totals, on='agent', how='left')
    grp['p'] = grp['w'] / grp['tot'].replace({0: np.nan})
    grp = grp.dropna(subset=['p'])
    # H_i
    H_i = (-grp['p'] * np.log(grp['p'])).groupby(grp['agent']).sum()
    # 加權平均（權重=該 agent 出度 tot）
    tot_deg = totals.reindex(H_i.index)
    H_bar = float((H_i * tot_deg).sum() / tot_deg.sum()) if tot_deg.sum() > 0 else 0.0
    # 規模化
    V = pd.unique(df[['agent','addressed_to']].values.ravel('K'))
    max_H = np.log(max(len(V)-1, 1))
    return float(H_bar / max_H) if max_H > 0 else 0.0

def _safe_json_list(x):
    """把字串形式的 JSON list 轉成 Python list；失敗回 []."""
    if isinstance(x, list):
        return x
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return []
    s = str(x)
    try:
        return json.loads(s)
    except Exception:
        try:
            return ast.literal_eval(s)
        except Exception:
            return []

# ========== 指標計算 ==========
def compute_bb_metrics(ev: pd.DataFrame) -> pd.DataFrame:
    """
    由 bb_write / bb_read 事件計算：
    - t_first_read_ms（中位數）
    - reuse_rate（有被他人讀過的 artifact 比例）
    - orphan_rate（從未被他人讀過的比例）
    """
    bb_w = ev[ev['event_type'] == 'bb_write'][['run_id','artifact_id','agent','timestamp_ms']].rename(
        columns={'agent':'writer','timestamp_ms':'t_write'})
    bb_r = ev[ev['event_type'] == 'bb_read'][['run_id','fact_ids_served','agent','timestamp_ms']].rename(
        columns={'agent':'reader','timestamp_ms':'t_read'}
    ).copy()

    if bb_w.empty:
        return pd.DataFrame(columns=['run_id','t_first_read_ms_median','reuse_rate','orphan_rate'])

    # explode reads
    bb_r['artifact_id_list'] = bb_r['fact_ids_served'].apply(_safe_json_list)
    bb_r = bb_r.explode('artifact_id_list').rename(columns={'artifact_id_list':'artifact_id'})
    bb_r = bb_r.dropna(subset=['artifact_id'])
    bb_r['artifact_id'] = bb_r['artifact_id'].astype(str)

    # join and filter self-reads
    jr = bb_r.merge(bb_w, on=['run_id','artifact_id'], how='left')
    if jr.empty:
        # 沒有人讀 → 全部 orphan
        out = bb_w.groupby('run_id').agg(
            t_first_read_ms_median=('t_write', lambda s: np.nan),
            reuse_rate=('artifact_id', lambda s: 0.0),
            orphan_rate=('artifact_id', lambda s: 1.0)
        ).reset_index()
        return out.rename(columns={'t_first_read_ms_median':'t_first_read_ms_median'})

    jr['is_other'] = (jr['reader'] != jr['writer'])
    jr = jr[jr['is_other']]

    # t_first_read
    t_first = jr.groupby(['run_id','artifact_id'])['t_read'].min().to_frame('t_first_read').reset_index() \
                .merge(bb_w, on=['run_id','artifact_id'], how='left')
    t_first['t_first_read_ms'] = t_first['t_first_read'] - t_first['t_write']

    # reuse / orphan
    reuse = jr.groupby(['run_id','artifact_id'])['reader'].nunique().to_frame('unique_readers').reset_index()
    bb = bb_w.merge(reuse, on=['run_id','artifact_id'], how='left')
    bb['unique_readers'] = bb['unique_readers'].fillna(0)
    bb['orphan'] = (bb['unique_readers'] == 0).astype(int)

    bb_run = bb.groupby('run_id').agg(
        reuse_rate=('unique_readers', lambda x: float(np.mean(x > 0))),
        orphan_rate=('orphan', 'mean')
    ).reset_index()

    tf_run = t_first.groupby('run_id').agg(
        t_first_read_ms_median=('t_first_read_ms', 'median')
    ).reset_index()

    out = bb_run.merge(tf_run, on='run_id', how='left')
    return out

def compute_topology_metrics(ev: pd.DataFrame) -> pd.DataFrame:
    """
    由 intent(delegate_to_*) 建立 handoff 邊，計算：
    - Freeman out-degree centralization（C_out）
    - handoff entropy（H）
    - workload Gini（全事件按 agent 聚合）
    """
    # 建立 handoff edges：intent + delegate_to_*
    intent = ev[(ev['event_type'] == 'intent') & (ev['tool_name'].fillna('').str.startswith('delegate_to_'))].copy()
    if intent.empty:
        # 退而求其次：用 addressed_to 不為空的事件做邊
        edges = ev[ev['addressed_to'].notna() & (ev['addressed_to'].astype(str).str.len() > 0)].copy()
        edges = edges.groupby(['run_id','agent','addressed_to']).size().to_frame('w').reset_index()
    else:
        intent['to'] = intent['tool_name'].str.rsplit('_', 1).str[-1].str.upper()
        edges = intent.groupby(['run_id','agent','to']).size().to_frame('w').reset_index() \
                      .rename(columns={'to':'addressed_to'})

    # 每 run 計 C/H
    ch_rows = []
    for rid, g in edges.groupby('run_id'):
        C = freeman_centralization_out(g[['agent','addressed_to','w']])
        H = handoff_entropy(g[['agent','addressed_to','w']])
        ch_rows.append({'run_id': rid, 'C_out': C, 'handoff_entropy': H})
    ch = pd.DataFrame(ch_rows) if ch_rows else pd.DataFrame(columns=['run_id','C_out','handoff_entropy'])

    # Workload Gini：以事件數（或 tokens）按 agent 聚合
    wl = ev.groupby(['run_id','agent']).size().to_frame('n').reset_index()
    gini_rows = []
    for rid, g in wl.groupby('run_id'):
        gini_rows.append({'run_id': rid, 'gini_workload': gini(g['n'].values)})
    gl = pd.DataFrame(gini_rows) if gini_rows else pd.DataFrame(columns=['run_id','gini_workload'])

    out = ch.merge(gl, on='run_id', how='outer')
    return out

# ========== 作圖 ==========
def plot_topology(df_run: pd.DataFrame, out_path: str, top_n: int = 20):
    """一張圖放 C_out / gini_workload / handoff_entropy（依 run 排名前 N）。"""
    if df_run.empty:
        return
    d = df_run[['run_id','C_out','gini_workload','handoff_entropy']].copy()
    d = d.fillna(0.0)
    # 依 C_out 排序取前 N（若 run 很多避免擁擠）
    d = d.sort_values('C_out', ascending=False).head(top_n)
    idx = np.arange(len(d))
    w = 0.25

    plt.figure(figsize=(12, 6))
    plt.bar(idx - w, d['C_out'].values, width=w, label='C_out')
    plt.bar(idx,      d['gini_workload'].values, width=w, label='Gini')
    plt.bar(idx + w, d['handoff_entropy'].values, width=w, label='H (handoff entropy)')
    plt.xticks(idx, d['run_id'].astype(str), rotation=45, ha='right')
    plt.title('Topology Metrics per Run (Top by C_out)')
    plt.ylabel('Value (0~1)')
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()

def plot_read_latency(df_run: pd.DataFrame, out_path: str):
    """各 run 的 t_first_read_ms 中位數（條形圖）。"""
    if df_run.empty or 't_first_read_ms_median' not in df_run.columns:
        return
    d = df_run[['run_id','t_first_read_ms_median']].dropna()
    if d.empty:
        return
    d = d.sort_values('t_first_read_ms_median', ascending=True)
    plt.figure(figsize=(12, 5))
    plt.barh(d['run_id'].astype(str), d['t_first_read_ms_median'].values)
    plt.xlabel('t_first_read (ms, median)')
    plt.title('First-Read Latency (Median) per Run')
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()

def plot_reuse_orphan(df_run: pd.DataFrame, out_path: str):
    """reuse_rate vs orphan_rate 散點圖。"""
    if df_run.empty:
        return
    d = df_run[['run_id','reuse_rate','orphan_rate']].dropna()
    if d.empty:
        return
    plt.figure(figsize=(7, 6))
    plt.scatter(d['reuse_rate'], d['orphan_rate'])
    for _, r in d.iterrows():
        plt.annotate(str(r['run_id'])[:6], (r['reuse_rate'], r['orphan_rate']), fontsize=8, alpha=0.7)
    plt.xlabel('reuse_rate')
    plt.ylabel('orphan_rate')
    plt.title('Reuse vs Orphan per Run')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=180)
    plt.close()

# ========== 主流程 ==========
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='in_path', required=True, help='events.parquet 路徑')
    ap.add_argument('--out_dir', required=True, help='輸出資料夾')
    ap.add_argument('--save_csv', action='store_true', help='同時輸出 run_metrics.csv')
    # 圖檔檔名（可自訂以對齊你的模板）
    ap.add_argument('--fig_topo', default='fig_topology_metrics.png')
    ap.add_argument('--fig_latency', default='fig_read_latency.png')
    ap.add_argument('--fig_reuse', default='fig_reuse_orphan.png')
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    ev = pd.read_parquet(args.in_path)
    # 必要欄位防呆
    need_cols = ['run_id','event_type','agent','addressed_to','tool_name','timestamp_ms','artifact_id','fact_ids_served']
    for c in need_cols:
        if c not in ev.columns:
            ev[c] = np.nan

    # 指標
    topo = compute_topology_metrics(ev)
    bb = compute_bb_metrics(ev)

    run_metrics = topo.merge(bb, on='run_id', how='outer')

    # 存檔
    out_parquet = os.path.join(args.out_dir, 'run_metrics.parquet')
    run_metrics.to_parquet(out_parquet, index=False)
    if args.save_csv:
        run_metrics.to_csv(os.path.join(args.out_dir, 'run_metrics.csv'), index=False, encoding='utf-8-sig')

    # 作圖
    plot_topology(run_metrics, os.path.join(args.out_dir, args.fig_topo))
    plot_read_latency(run_metrics, os.path.join(args.out_dir, args.fig_latency))
    plot_reuse_orphan(run_metrics, os.path.join(args.out_dir, args.fig_reuse))

    print(f"[OK] wrote metrics → {out_parquet}")
    print(f"[OK] figures → {args.fig_topo}, {args.fig_latency}, {args.fig_reuse}")

if __name__ == '__main__':
    main()
