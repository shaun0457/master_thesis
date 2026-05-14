"""Minimal monitoring dashboard — HTML served by FastAPI at GET /dashboard.

Shows the last N diagnoses with predicted vs true fault, rolling accuracy,
and live observation count. Deliberately dependency-free (vanilla HTML +
inline CSS); no Streamlit, no JS framework.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import os
import sqlite3
from typing import Any

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUFFER_DB = os.path.join(BASE, "live_observations.db")


def _safe(s: Any) -> str:
    return html.escape(str(s)) if s is not None else "—"


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "—"
    try:
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return _safe(ts)


def _verdict(pred: int | None, truth: int | None) -> tuple[str, str]:
    if truth is None:
        return ("—", "neutral")
    if pred is None:
        return ("missing", "wrong")
    return ("✓", "ok") if int(pred) == int(truth) else ("✗", "wrong")


def render_dashboard(buffer_db: str = BUFFER_DB, limit: int = 50) -> str:
    if not os.path.exists(buffer_db):
        return _shell("No live buffer yet — run scripts/init_live_buffer.py first.",
                      total_obs=0, accuracy=None, rows_html="")

    conn = sqlite3.connect(buffer_db)
    try:
        diagnoses = conn.execute(
            "SELECT run_id, ts, predicted_fault, confidence, evidence_json, "
            "summary, true_fault_optional "
            "FROM diagnoses ORDER BY ts DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        obs_count = conn.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0]
    finally:
        conn.close()

    correct = 0
    with_truth = 0
    rows: list[str] = []
    for run_id, ts, pred, conf, evidence_json, summary, truth in diagnoses:
        if truth is not None:
            with_truth += 1
            if pred is not None and int(pred) == int(truth):
                correct += 1
        verdict, css = _verdict(pred, truth)
        ev = ""
        try:
            ev_obj = json.loads(evidence_json or "{}")
            sensors = ev_obj.get("sensors") or []
            ev = ", ".join(sensors[:5])
        except Exception:
            ev = "—"
        rows.append(_row_html(run_id, ts, pred, truth, conf, ev, summary, verdict, css))

    accuracy = (correct / with_truth) if with_truth else None
    return _shell(
        f"{len(diagnoses)} recent diagnoses · "
        f"{correct}/{with_truth} correct"
        + (f" · accuracy {accuracy:.1%}" if accuracy is not None else ""),
        total_obs=obs_count,
        accuracy=accuracy,
        rows_html="\n".join(rows),
    )


def _row_html(
    run_id: str,
    ts: float,
    pred: int | None,
    truth: int | None,
    conf: float | None,
    evidence: str,
    summary: str | None,
    verdict: str,
    css: str,
) -> str:
    summary_short = (summary or "")[:140].replace("\n", " ")
    if summary and len(summary) > 140:
        summary_short += "…"
    conf_pct = f"{conf:.0%}" if conf is not None else "—"
    return f"""
<tr class="{css}">
  <td class="mono">{_safe(run_id)}</td>
  <td>{_fmt_ts(ts)}</td>
  <td class="num">{_safe(pred)}</td>
  <td class="num">{_safe(truth)}</td>
  <td class="verdict">{verdict}</td>
  <td class="num">{conf_pct}</td>
  <td class="mono small">{_safe(evidence)}</td>
  <td class="small">{_safe(summary_short)}</td>
</tr>"""


def _shell(subtitle: str, total_obs: int, accuracy: float | None, rows_html: str) -> str:
    acc_badge = ""
    if accuracy is not None:
        acc_color = "#22c55e" if accuracy >= 0.7 else ("#f59e0b" if accuracy >= 0.4 else "#ef4444")
        acc_badge = f'<span class="badge" style="background:{acc_color}">{accuracy:.1%}</span>'
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>TEP Diagnosis Monitor</title>
<meta http-equiv="refresh" content="10">
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 24px; color: #1f2937; background: #f9fafb; }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  .sub {{ color: #6b7280; margin-bottom: 16px; }}
  .stats {{ display: flex; gap: 12px; margin-bottom: 20px; }}
  .card {{ background: white; padding: 12px 16px; border: 1px solid #e5e7eb;
          border-radius: 6px; min-width: 140px; }}
  .card .label {{ font-size: 11px; color: #6b7280; text-transform: uppercase; }}
  .card .value {{ font-size: 22px; font-weight: 600; margin-top: 4px; }}
  .badge {{ color: white; padding: 2px 8px; border-radius: 99px;
            font-size: 13px; margin-left: 6px; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden;
           font-size: 13px; }}
  th, td {{ padding: 6px 10px; text-align: left;
            border-bottom: 1px solid #f3f4f6; }}
  th {{ background: #f3f4f6; font-weight: 600; color: #374151; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.verdict {{ text-align: center; font-size: 15px; }}
  td.mono {{ font-family: SFMono-Regular, Menlo, monospace; font-size: 11px; }}
  td.small {{ font-size: 11px; color: #4b5563; max-width: 360px; }}
  tr.ok {{ background: #f0fdf4; }}
  tr.wrong {{ background: #fef2f2; }}
  tr.neutral {{ background: white; }}
  .empty {{ padding: 40px; text-align: center; color: #9ca3af; }}
</style>
</head><body>
<h1>TEP Diagnosis Monitor {acc_badge}</h1>
<div class="sub">{subtitle} · refreshes every 10 s</div>
<div class="stats">
  <div class="card"><div class="label">Live observations</div>
    <div class="value">{total_obs:,}</div></div>
  <div class="card"><div class="label">Rolling accuracy</div>
    <div class="value">{(f"{accuracy:.1%}" if accuracy is not None else "—")}</div></div>
</div>
{('<table><tr><th>Run</th><th>When</th><th>Predicted</th><th>True</th>'
  '<th>·</th><th>Conf</th><th>Evidence sensors</th><th>Summary</th></tr>'
  + rows_html + '</table>') if rows_html else '<div class="empty">No diagnoses yet.</div>'}
</body></html>"""
