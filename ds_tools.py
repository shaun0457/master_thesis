# ds_tools.py
from typing import List, Optional
from langchain_core.tools import tool
from bb_tools import (
    bb_find_dataset_py,
    bb_get_latest_dataset,
    bb_list_datasets,
    bb_list_datasets_py,
    bb_preview_dataset,
)
from run_logger import get_run_logger
import os
import json


def _resolve_path(it: dict) -> Optional[str]:
    ref = it.get("ref")
    if isinstance(ref, str) and os.path.exists(ref):
        return ref

    uri = it.get("uri")
    if isinstance(uri, str) and os.path.exists(uri):
        return uri

    if isinstance(uri, dict):
        p = uri.get("path")
        if isinstance(p, str) and os.path.exists(p):
            return p
    return None


@tool
def ds_pick_dataset_path(prefer_topic: str = "") -> str:
    """
    Return the best available dataset path from the canonical blackboard registry.

    `prefer_topic` is kept for backward compatibility, but matching now prefers
    dataset identity (`name` / aliases) before workflow topic.
    """
    get_run_logger()
    run_id = os.getenv("RUN_ID", "default")
    items = bb_list_datasets_py(run_id)

    match = bb_find_dataset_py(run_id, prefer_name=prefer_topic, prefer_topic=prefer_topic)
    if match:
        p = _resolve_path(match)
        if p:
            return json.dumps({"status": "ok", "path": p}, ensure_ascii=False)

    for it in reversed(items):
        p = _resolve_path(it)
        if p:
            return json.dumps({"status": "ok", "path": p}, ensure_ascii=False)

    return json.dumps({"status": "empty"}, ensure_ascii=False)


def _execute_python_subprocess(code: str, timeout: int = 30) -> dict:
    """Run code in a subprocess for isolation and timeout safety."""
    import subprocess
    import tempfile
    import sys as _sys

    def _looks_secret(key: str) -> bool:
        upper_key = str(key or "").upper()
        return any(token in upper_key for token in ("TOKEN", "KEY", "SECRET", "PASSWORD", "CREDENTIAL"))

    clean_env = {}
    for key in ("PATH", "PYTHONPATH", "TMPDIR"):
        value = os.environ.get(key)
        if value and not _looks_secret(key):
            clean_env[key] = value
    clean_env["PATH"] = os.environ.get("PATH") or os.environ.get("Path", "")
    clean_env["PYTHONPATH"] = os.getcwd()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [_sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=clean_env,
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
    """Execute Python code in an isolated subprocess sandbox and return text result."""
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
