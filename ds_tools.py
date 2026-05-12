# ds_tools.py (最终修正版 - 使用自定义工具)
from typing import List, Optional
from langchain_core.tools import tool
from bb_tools import bb_list_datasets, bb_get_latest_dataset, bb_preview_dataset, bb_list_datasets_py
from run_logger import get_run_logger
import os, json

def _resolve_path(it: dict) -> Optional[str]:
    # 1) 優先用 datasets 的 ref（字串路徑）
    ref = it.get("ref")
    if isinstance(ref, str) and os.path.exists(ref):
        return ref
    # 2) 退而求其次：artifacts 鏡射的 uri（字串）
    uri = it.get("uri")
    if isinstance(uri, str) and os.path.exists(uri):
        return uri
    # 3) 歷史相容：有些舊資料把 uri 存成 dict
    if isinstance(uri, dict):
        p = uri.get("path")
        if isinstance(p, str) and os.path.exists(p):
            return p
    return None

@tool
def ds_pick_dataset_path(prefer_topic: str = "") -> str:
    """
    根據目前 RUN_ID 的 blackboard，挑一個可讀取的 dataset 檔案路徑（字串）。
    - 若提供 prefer_topic，先找 topic_id 相符者；否則回退到最後一筆可讀路徑。
    回傳 JSON: {"status":"ok","path":"..."} 或 {"status":"empty"}。
    """
    rl = get_run_logger()
    run_id = os.getenv("RUN_ID", "default")
    items = bb_list_datasets_py(run_id)

    # 1) 先依 topic 過濾（若有）
    if prefer_topic:
        for it in reversed(items):
            if it.get("topic_id") == prefer_topic:
                p = _resolve_path(it)
                if p:
                    return json.dumps({"status":"ok","path": p}, ensure_ascii=False)

    # 2) 回退：從最後一筆往前找第一個可讀路徑
    for it in reversed(items):
        p = _resolve_path(it)
        if p:
            return json.dumps({"status":"ok","path": p}, ensure_ascii=False)

    return json.dumps({"status":"empty"}, ensure_ascii=False)

def _execute_python_subprocess(code: str, timeout: int = 30) -> dict:
    """Run code in a subprocess for isolation and timeout safety."""
    import subprocess
    import tempfile
    import sys as _sys
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [_sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": os.getcwd()},
        )
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@tool
def execute_python_code(code: str) -> str:
    """
    Execute Python code in an isolated subprocess sandbox and return text result.
    """
    rl = get_run_logger()
    task_id = os.getenv("TASK_ID")
    try:
        with rl.tool_exec(agent="DS", tool="execute_python_code", task_id=task_id, args={"code_len": len(code or "")}) as t:
            result = _execute_python_subprocess(code, timeout=30)
            ok = "error" not in result and result.get("returncode", 0) == 0
            t.ok(ok)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        rl.error_event(agent="DS", kind="python_error", message=f"{type(e).__name__}: {e}", task_id=task_id, recovered=False, exc=e)
        with rl.tool_exec(agent="DS", tool="execute_python_code", task_id=task_id, args={"err": str(e)}) as t:
            t.ok(False)
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)

def get_ds_tools(mode: str = "augmented") -> (list, dict):
    tools = [execute_python_code, bb_list_datasets, bb_get_latest_dataset, bb_preview_dataset, ds_pick_dataset_path]
    tool_map = {t.name: t for t in tools}
    return tools, tool_map