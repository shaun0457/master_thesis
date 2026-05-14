# de_tools.py
import re, uuid, time
from sqlalchemy import create_engine, text, inspect
from langchain.tools import tool
from bb_tools import bb_register_dataset
import os, json, pandas as pd
from typing import Dict, Any, List, Optional
from run_logger import get_run_logger
from bb_tools import _write_to_blackboard_impl as _bb_write   # 程式 API 版
from bb_tools import bb_register_dataset_path





# DB 连线：现在只在这里定义
# tep_combined.db 包含 IDV=0 (250K rows) + IDV 1-20 (25K rows each)
DB_URL = os.environ.get("DATABASE_URL", "sqlite:///tep_combined.db")
ENGINE = create_engine(DB_URL, pool_pre_ping=True)
FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", re.I)
_LEADING_SQL_COMMENTS = re.compile(r"^(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/)+", re.DOTALL)

def _get_db_engine():
    db_url = os.getenv("DATABASE_URL") or "sqlite:///tep_combined.db"
    return create_engine(db_url, future=True)

def _to_json_payload(df: pd.DataFrame) -> str:
    preview = df.head(5000)
    return json.dumps({
        "status": "ok",
        "columns": list(preview.columns),
        "rowcount": int(len(df)),
        "rows": preview.to_dict(orient="records")
    }, ensure_ascii=False)

# def _norm_arg_str(x, key: str | None = None) -> str:
#     if isinstance(x, dict): return x.get(key) or x.get("query") or ""
#     if isinstance(x, str): return x
#     return str(x or "")

def _norm_arg_str(x: Any, key: Optional[str] = None) -> str:   # ✅ 不用 str | None
    if isinstance(x, dict):
        if key and x.get(key) is not None:
            return str(x.get(key))
        for k in ("query", "sql", "value", "table_name"):
            if x.get(k) is not None:
                return str(x.get(k))
        return ""
    if isinstance(x, (list, tuple, set)):
        return ", ".join(map(str, x))
    if x is None:
        return ""
    return str(x)


def _strip_leading_sql_comments(query: str) -> str:
    stripped = query or ""
    while True:
        updated = _LEADING_SQL_COMMENTS.sub("", stripped, count=1)
        if updated == stripped:
            return stripped.lstrip()
        stripped = updated


_MAX_QUERY_ROWS = int(os.environ.get("DE_MAX_ROWS", "10000"))
_HAS_LIMIT = re.compile(r"\bLIMIT\b", re.IGNORECASE)

def _validate_read_only_select(query: str) -> str:
    normalized = _strip_leading_sql_comments(str(query or ""))
    if not normalized or not normalized.lower().startswith("select") or FORBIDDEN.search(normalized):
        raise ValueError("Only read-only SELECT queries are allowed.")
    if not _HAS_LIMIT.search(normalized):
        normalized = normalized.rstrip().rstrip(";") + f" LIMIT {_MAX_QUERY_ROWS}"
    return normalized

@tool
def sql_db_query(query: str) -> str:
    """
    執行 SQL 查詢並回傳結果（JSON 字串）。
    查詢成功後，若環境變數 DE_AUTOREGISTER=1（預設），
    會自動將「輕量樣本」註冊為 dataset（最小保險絲），
    以避免 DS 因 DE 未顯式交付而完全拿不到資料。

    關閉自動註冊：將環境變數 DE_AUTOREGISTER 設為 "0"。
    """
    rl = get_run_logger()
    with rl.tool_exec(agent="DE", tool="sql_db_query", task_id=os.getenv("TASK_ID"), args={"query": query}) as t:
        try:
            query_str = _validate_read_only_select(query)

            eng = _get_db_engine()
            with eng.connect().execution_options(no_cache_on_overflow=True) as conn:
                if eng.dialect.name == "sqlite":
                    conn.exec_driver_sql("PRAGMA query_only = ON")
                rows_raw = conn.execute(text(query_str)).mappings().all()

            rows = [dict(r) for r in rows_raw]
            cols = list(rows[0].keys()) if rows else []
            out: Dict[str, Any] = {
                "status": "ok",
                "columns": cols,
                "rowcount": len(rows),
                "rows": rows[:1000],
            }

            if os.getenv("DE_AUTOREGISTER", "1") == "1":
                try:
                    run_id = os.getenv("RUN_ID") or f"run_{uuid.uuid4().hex[:8]}"
                    topic_id = os.getenv("TOPIC_ID", "")
                    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)
                    dataset_name = f"de_autosample_{abs(hash(query_str)) & 0xFFFF}"
                    out_dir = os.path.join("datasets", run_id)
                    os.makedirs(out_dir, exist_ok=True)
                    parquet_path = os.path.join(out_dir, f"{dataset_name}.parquet")
                    df.to_parquet(parquet_path, index=False)

                    _ = bb_register_dataset_path(
                        run_id=run_id,
                        name=dataset_name,
                        path=parquet_path,
                        fmt="parquet",
                        rows=len(df),
                        columns=list(df.columns),
                        meta={"source": "sql_db_query", "sampled": True, "intended_owner": "DS"},
                        topic_id=topic_id,
                        created_by="DE"
                    )
                    out["df_payload"] = {"name": dataset_name, "path": parquet_path, "run_id": run_id}
                except Exception as _e:
                    out["df_register_error"] = str(_e)

            t.ok(True)
            return json.dumps(out, ensure_ascii=False)
        except Exception as e:
            t.ok(False)
            return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

# @tool
# def sql_db_query(query: str) -> str:
#     """
#     執行 SQL 查詢並回傳結果（JSON 字串）。
#     查詢成功後，若環境變數 DE_AUTOREGISTER=1（預設），
#     會自動將「輕量樣本」註冊為 dataset（最小保險絲），
#     以避免 DS 因 DE 未顯式交付而完全拿不到資料。
#
#     關閉自動註冊：將環境變數 DE_AUTOREGISTER 設為 "0"。
#     """
#     rl = get_run_logger()
#     with rl.tool_exec(agent="DE", tool="sql_db_query", task_id=os.getenv("TASK_ID"), args={"query": query}) as t:
#         try:
#             # 1) 僅允許 SELECT
#             if FORBIDDEN.search(query) or not query.strip().lower().startswith("select"):
#                 raise ValueError("Only read-only SELECT queries are allowed.")
#
#             eng = _get_db_engine()
#
#             # 2) 執行查詢（只做一次）
#             with eng.connect() as conn:
#                 rows_raw = conn.execute(text(query)).mappings().all()
#             rows = [dict(r) for r in rows_raw]
#             cols = list(rows[0].keys()) if rows else []
#
#             out: Dict[str, Any] = {
#                 "status": "ok",
#                 "columns": cols,
#                 "rowcount": len(rows),
#                 "rows": rows[:1000],  # 回傳最多 1000 筆，避免輸出過大
#             }
#
#             # 3) 自動註冊樣本（可關）
#             if os.getenv("DE_AUTOREGISTER", "1") == "1":
#                 try:
#                     run_id = os.getenv("RUN_ID") or f"run_{uuid.uuid4().hex[:8]}"
#                     df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)
#
#                     dataset_name = f"de_autosample_{abs(hash(query)) & 0xFFFF}"
#                     out_dir = os.path.join("datasets", run_id)
#                     os.makedirs(out_dir, exist_ok=True)
#                     parquet_path = os.path.join(out_dir, f"{dataset_name}.parquet")
#                     df.to_parquet(parquet_path, index=False)
#
#                     try:
#                         from bb_tools import bb_register_dataset_path  # helper（非 Tool）
#                         bb_register_dataset_path(
#                             run_id, dataset_name, parquet_path,
#                             meta={"source": "sql_db_query", "sampled": True}
#                         )
#                     except Exception:
#                         # 退而求其次：若你把 deliver_dataframe 暴露為 Tool
#                         try:
#                             _ = deliver_dataframe.invoke({
#                                 "name": dataset_name,
#                                 "path": parquet_path,
#                                 "meta": {"source": "sql_db_query", "sampled": True}
#                             })
#                         except Exception:
#                             pass
#
#                     # 讓上層 Router/DS 即使不讀黑板，也能直接取得檔案位置
#                     out["df_payload"] = {"name": dataset_name, "path": parquet_path, "run_id": run_id}
#                 except Exception as _e:
#                     out["df_register_error"] = str(_e)
#
#             t.ok(True)
#             return json.dumps(out, ensure_ascii=False)
#
#         except Exception as e:
#             t.ok(False)
#             return json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)

# @tool
# def sql_db_list_tables() -> str:
#     """List available tables."""
#     print("--- 外部工具: 列出資料表 ---")
#     try:
#         insp = inspect(ENGINE)
#         tables = [{"table": t} for t in insp.get_table_names()]
#         return json.dumps({"status": "ok", "tables": tables}, ensure_ascii=False)
#     except Exception as e:
#         return json.dumps({"status": "error", "error": str(e)})

@tool
def sql_db_list_tables() -> str:
    """List available tables."""
    print("--- 外部工具: 列出資料表 ---")
    try:
        insp = inspect(_get_db_engine())  # ← 改這行
        tables = [{"table": t} for t in insp.get_table_names()]
        return json.dumps({"status": "ok", "tables": tables}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

@tool
def sql_db_schema(table_name: str) -> str:
    """Get column names and types for a given table."""
    table = _norm_arg_str(table_name, "table_name")
    print(f"--- 外部工具: 讀取 Schema: '{table}' ---")
    try:
        insp = inspect(_get_db_engine())  # ← 改這行
        cols = [{"name": c["name"], "type": str(c["type"])} for c in insp.get_columns(table)]
        return json.dumps({"status": "ok", "table": table, "columns": cols}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{e.__class__.__name__}: {e}"})

@tool
def sql_db_schema(table_name: str) -> str:
    """Get column names and types for a given table."""
    table = _norm_arg_str(table_name, "table_name")
    print(f"--- 外部工具: 讀取 Schema: '{table}' ---")
    try:
        insp = inspect(ENGINE)
        cols = [{"name": c["name"], "type": str(c["type"])} for c in insp.get_columns(table)]
        return json.dumps({"status": "ok", "table": table, "columns": cols}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"{e.__class__.__name__}: {e}"})


@tool
def pandas_transform(df_json: str, operations: Optional[List[str]] = None) -> str:  # ✅ 去掉 list[str] | None
    """Apply transformation operations on a DataFrame and return JSON."""
    print("--- External tool: pandas_transform called ---")
    try:
        data = json.loads(df_json)
        if data.get("status") != "ok":
            raise ValueError("Input must be valid DF JSON.")
        df = pd.DataFrame(data["rows"])
        allowed_ops = {"rename", "cast", "select", "dropna", "to_numeric", "parse_mmss_to_hhmmss"}
        for op in (operations or []):  # ✅ operations 可能是 None
            op_type = op.split(":", 1)[0].strip().lower()
            if op_type not in allowed_ops:
                raise ValueError(f"Operation '{op_type}' not allowed. Only {sorted(allowed_ops)}.")
            if op_type == "rename":
                _, mapping = op.split(":", 1)
                rename_dict = dict(pair.split("->") for pair in mapping.split(","))
                df = df.rename(columns={k.strip(): v.strip() for k, v in rename_dict.items()})
            elif op_type == "cast":
                _, col_type = op.split(":", 1)
                col, dtype = [s.strip() for s in col_type.split("=")]
                df[col] = df[col].astype(dtype)
            elif op_type == "select":
                _, cols = op.split(":", 1)
                cols = [c.strip() for c in cols.split(",")]
                df = df[cols]
            elif op_type == "dropna":
                _, rest = (op.split(":", 1) + [""])[0:2]
                subset = [c.strip() for c in rest.split(",")] if rest else None
                df = df.dropna(subset=subset)
            elif op_type == "to_numeric":
                _, spec = op.split(":", 1)
                col = spec.split("=")[1].strip()
                df[col] = pd.to_numeric(df[col], errors="coerce")
            elif op_type == "parse_mmss_to_hhmmss":
                _, spec = op.split(":", 1)
                parts = dict(p.split("=") for p in spec.split(","))
                src = parts["src"].strip()
                target = parts.get("target", "timestamp").strip()
                s = df[src].astype(str).str.replace(r"\.0$", "", regex=True)
                df[target] = s.apply(lambda v: v if v.count(":") == 2 else f"00:{v}")

        return json.dumps({
            "status": "ok",
            "columns": list(df.columns),
            "rowcount": int(len(df)),
            "rows": df.to_dict(orient="records")
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

def _auto_publish_dataset(df, state: Dict[str, Any], *, agent: str = "DE", name_prefix: str = "de_autosample") -> Dict[str, Any]:
    """把 df 落成 parquet + 註冊到黑板 + 發一則黑板訊息；失敗就靜默略過（不影響原有邏輯）"""
    try:
        run_id = state.get("run_id") or os.getenv("RUN_ID") or time.strftime("%Y%m%d_%H%M%S")
        folder = os.path.join("datasets", run_id)
        os.makedirs(folder, exist_ok=True)

        fname = f"{name_prefix}_{uuid.uuid4().hex[:6]}.parquet"
        ref = os.path.join(folder, fname).replace("\\", "/")

        # 1) 存檔
        df.to_parquet(ref, index=False)

        # 2) 在 state.blackboard.datasets 鏡射（DS 的 bb_list_datasets 會看得到）
        meta = {
            "id": f"ds_{uuid.uuid4().hex[:8]}",
            "artifact_id": f"fx_{uuid.uuid4().hex[:16]}",
            "name": os.path.splitext(os.path.basename(ref))[0],
            "ref": ref,
            "format": "parquet",
            "rows": int(getattr(df, "shape", [0, 0])[0]),
            "schema": None,
            "created_ms": int(time.time() * 1000),
            "agent": agent,
            "desc": None,
            "meta": {"source": "sql_db_query", "sampled": True},
            "topic_id": "",
        }
        state.setdefault("blackboard", {}).setdefault("datasets", []).append(meta)

        # 3) 一行保險：同步發一則黑板訊息（DS/ME 會在 facts/datasets 區看到）
        # if _bb_write:
        #     _bb_write(
        #         section="datasets",
        #         summary=f"{agent} published {os.path.basename(ref)}",
        #         content={"df_payload": {k: v for k, v in meta.items() if k in ("ref", "format", "rows", "name")}},
        #         state=state,
        #     )

        if _bb_write:
            _bb_write(
                section="datasets",
                summary=f"{agent} published {os.path.basename(ref)}",
                content={"df_payload": {k: v for k, v in meta.items() if k in ("ref", "format", "rows", "name")}},
                state=state,  # 有 state 就順便鏡射
                created_by=agent
            )

        return meta
    except Exception:
        return {}


@tool
def deliver_dataframe(df_json: str) -> str:
    """Deliver a DataFrame-like JSON as dataset and return a reference path."""
    import json, pandas as pd, os
    rl = get_run_logger(); task_id = os.getenv("TASK_ID")
    try:
        data = json.loads(df_json)
        if data.get("status") != "ok":
            raise ValueError("Input must be a valid DF JSON with status=ok.")
        rows = data.get("rows")
        if rows is None:
            raise ValueError("Missing 'rows'")
        df = pd.DataFrame(rows)

        fmt = "parquet"
        run_id = os.getenv("RUN_ID") or "default"
        out_dir = os.path.join("datasets", run_id)
        os.makedirs(out_dir, exist_ok=True)
        parquet_path = os.path.join(out_dir, f"deliver_{abs(hash(df_json)) & 0xFFFF}.parquet")
        df.to_parquet(parquet_path, index=False)  # ← index=False

        ref = {"name": os.path.basename(parquet_path), "path": parquet_path, "run_id": run_id}

        # 優先用 helper；失敗再退回 Tool 版本
        try:
            from bb_tools import bb_register_dataset_path
            bb_register_dataset_path(run_id, ref["name"], parquet_path,
                                     meta={"source": "deliver_dataframe", "sampled": False})
        except Exception:
            try:
                from bb_tools import bb_register_dataset
                bb_register_dataset.invoke({
                    "ref": parquet_path, "fmt": "parquet", "rows": int(len(df)),
                    "columns": list(map(str, df.columns))
                })
            except Exception:
                pass

        try:
            rl.artifact(task_id=task_id, type_="dataset", path_or_hash=parquet_path,
                        preview_stats={"rows": int(len(df)), "cols": int(getattr(df,'shape',[0,0])[1])})
            with rl.tool_exec(agent="DE", tool="deliver_dataframe", task_id=task_id, args={"path": parquet_path}) as t:
                t.ok(True)
        except Exception:
            pass

        return json.dumps({"status": "ok", "df_payload": ref, "format": fmt, "rowcount": int(len(df))}, ensure_ascii=False)

    except Exception as e:
        try:
            rl.error_event(agent="DE", kind="deliver_error", message=str(e), task_id=task_id, recovered=False, exc=e)
            with rl.tool_exec(agent="DE", tool="deliver_dataframe", task_id=task_id, args={"err": str(e)}) as t:
                t.ok(False)
        except Exception:
            pass
        return json.dumps({"status": "error", "error": str(e)})

def get_de_tools(mode: str):
    """根据模式返回 DE 代理人专用的工具集。"""
    tools = ([
        sql_db_query,
        sql_db_list_tables,
        sql_db_schema,
        deliver_dataframe,
        pandas_transform
    ])
    tool_map = {t.name: t for t in tools}
    return tools, tool_map



