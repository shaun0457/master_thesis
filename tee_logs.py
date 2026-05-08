# common.py 末尾或新檔 tee_logs.py
import os, sys, io, contextlib

class _TeeStream:
    """把寫入的文字複製到多個 stream（例如：原本的 stdout + 檔案）。"""
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]
        self.encoding = "utf-8"

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
            except Exception:
                pass
        self.flush()

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        # 回報 False，避免某些套件以為是互動式終端
        return False

    # 兼容少數會呼叫 fileno() 的庫
    def fileno(self):
        for s in self.streams:
            if hasattr(s, "fileno"):
                try:
                    return s.fileno()
                except Exception:
                    continue
        raise OSError("fileno not available")

@contextlib.contextmanager
def tee_console_logs(run_id: str, log_dir: str, also_console: bool = True):
    """
    將整個 with 區塊內的 print()/stderr 以「tee」方式寫到檔案。
    也可選擇同時在主控台顯示（also_console=True）。
    """
    os.makedirs(log_dir, exist_ok=True)
    stdout_path = os.path.join(log_dir, f"{run_id}_stdout.txt")
    stderr_path = os.path.join(log_dir, f"{run_id}_stderr.txt")

    # 行緩衝，崩潰時也能保住絕大部分內容
    f_out = open(stdout_path, "a", encoding="utf-8", buffering=1)
    f_err = open(stderr_path, "a", encoding="utf-8", buffering=1)

    orig_out, orig_err = sys.stdout, sys.stderr
    try:
        sys.stdout = _TeeStream(orig_out if also_console else None, f_out)
        sys.stderr = _TeeStream(orig_err if also_console else None, f_err)
        yield {"stdout_path": stdout_path, "stderr_path": stderr_path}
    finally:
        # 還原
        sys.stdout, sys.stderr = orig_out, orig_err
        try:
            f_out.flush(); f_out.close()
        finally:
            pass
        try:
            f_err.flush(); f_err.close()
        finally:
            pass

def read_tail(path: str, tail_bytes: int = 4096) -> str:
    """讀取檔案最後 tail_bytes 的內容，便於寫入 JSON 摘要而不爆體積。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > tail_bytes:
                f.seek(size - tail_bytes)
            data = f.read()
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""
