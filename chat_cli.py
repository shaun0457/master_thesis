# chat_cli.py (防中断、防循环、带回合计数器的最终版)
import os
import json
from dotenv import load_dotenv
load_dotenv()
import uuid
import datetime
import traceback
from typing import Any, Dict, List
import argparse
from tee_logs import tee_console_logs, read_tail
from common import ensure_run_id, get_env_int, get_seed
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from metrics import init_metrics, finalize_metrics, update_me_citation_metrics
from run_logger import get_run_logger, begin_run, emit_run_meta, emit_outcome, end_run
# 假设 supervisor_workflow.py 已经包含了我们之前讨论的 Correction Node 版本
from supervisor_workflow import build_team_graph

LOG_DIR = "interactive_logs"
RUN_LOG_DIR = "run_logs"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(RUN_LOG_DIR, exist_ok=True)
DATA_DB = "sqlite:///tep_combined.db"


# ----- 辅助函数 (保持不变) -----
def _now():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _serialize_msg(m: BaseMessage) -> Dict[str, Any]:
    d: Dict[str, Any] = {"type": m.__class__.__name__, "content": getattr(m, "content", None)}
    if isinstance(m, AIMessage):
        d["tool_calls"] = getattr(m, "tool_calls", None)
    if isinstance(m, ToolMessage):
        d["name"] = getattr(m, "name", None)
        d["tool_call_id"] = getattr(m, "tool_call_id", None)
    return d


def _serialize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(state)
    out["messages"] = [_serialize_msg(m) for m in state.get("messages", [])]
    return out


def _save_session(session_id: str, state: Dict[str, Any], tag: str = "") -> str:
    # 确保 state 中有内容可写
    if not state.get("messages"):
        return "(No messages to save)"
    fname = f"{LOG_DIR}/chat_{session_id}_{_now()}{('_' + tag) if tag else ''}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(_serialize_state(state), f, ensure_ascii=False, indent=2)
    return fname


def _print_last(supervisor_state: Dict[str, Any]) -> None:
    msgs: List[BaseMessage] = supervisor_state.get("messages", [])
    if not msgs:
        print("\n[System] 無輸出。")
        return
    for m in reversed(msgs):
        if isinstance(m, AIMessage):
            if m.tool_calls and m.tool_calls[0]['name'] == 'final_answer':
                final_answer = m.tool_calls[0]['args'].get('answer', 'Final answer content not found.')
                print("\n[Supervisor FINAL ANSWER]\n" + final_answer)
            else:
                # 如果没有工具调用，就打印 content
                if not m.tool_calls:
                    print("\n[Supervisor Clarification]\n" + (m.content or "").strip())
                else:
                    print("\n[Supervisor Thought] " + (m.content or "").strip())
            return

def _print_recent_tool_events(state: Dict[str, Any], limit: int = 12) -> None:
    evs = state.get("tool_events", [])
    if not evs:
        return
    print("\n[Recent tool events]")
    for ev in evs[-limit:]:
        tool = ev.get("tool")
        latency = ev.get("latency_ms")
        agent = ev.get("agent") or "?"
        head = (ev.get("output_head") or "")[:140].replace("\n", " ")
        print(f" - ({agent}) {tool} [{latency}ms] :: {head}")

def _print_blackboard_summary(state: Dict[str, Any]) -> None:
    bb = state.get("blackboard", {})
    if not bb:
        return
    facts = bb.get("facts", [])
    datasets = bb.get("datasets", [])
    arts = bb.get("artifacts", [])
    print("\n[Blackboard summary]")
    print(f" - facts={len(facts)}  datasets={len(datasets)}  artifacts={len(arts)}")
    if arts:
        for a in arts[-3:]:
            print(f"   · figure: {a.get('path')} (by={a.get('by')})")

def _init_run_logger_from_cli(state, args):
    rl = get_run_logger()
    try:
        rl.set_policy(state.get("policy") or getattr(args, "policy", None))
        rl.set_model_params(
            model=os.getenv("GEMINI_MODEL","gemini-2.5-pro"),
            temperature=float(os.getenv("GEMINI_TEMP","0.25")),
            top_p=float(os.getenv("GEMINI_TOP_P","1.0")),
            max_tokens=int(os.getenv("GEMINI_MAX_TOK", "8192") or 8192)
        )
    except Exception:
        pass

def _finalize_run_logger(state):
    rl = get_run_logger()
    try:
        rl.attach_legacy("tool_events_legacy", state.get("tool_events", []))
        rl.data["messages"] = rl.data.get("messages") or []
        rl.data["blackboard"] = rl.data.get("blackboard") or {}
        rl.flush()
    except Exception:
        pass

def _read_user_block() -> str:
    """
    一行模式：正常輸入。
    貼上模式：先輸入 '<<<'，貼多行，最後輸入 '>>>' 結束。
    會把中間的多行用 '\n' 合併成一則訊息。
    """
    first = input("\n你 > ").rstrip("\n")
    if first.strip() != "<<<":
        return first.strip()

    print("(貼上模式開始：貼你的多行指令；單獨輸入 >>> 結束)")
    lines = []
    while True:
        line = input("")
        if line.strip() == ">>>":
            break
        lines.append(line)
    msg = "\n".join(lines).strip()
    print("(貼上模式結束)")
    return msg

def main():
    # 1. 解析命令行参数
    parser = argparse.ArgumentParser(description="Interactive CLI for the MAS team.")
    parser.add_argument("--policy", choices=["strict", "gentle", "free"], default="free",
                        help="Set the supervisor's intervention policy.")
    args = parser.parse_args()

    # 2. 初始化基本信息
    print("=== MAS 互動模式（Gemini）=== ")
    print(f"*** Running in '{args.policy}' policy mode ***")

    PDF_DOCS_PATH = "TEP_docs"
    SQLITE_DB_PATH = DATA_DB

    session_id = f"{_now()}_{uuid.uuid4().hex[:8]}"
    os.environ["RUN_ID"] = session_id

    # === 讀入 meta（可被 .bat/.ps1 覆寫） ===
    seed = get_env_int("SEED", 11)
    task_id = os.getenv("TASK_ID", "Q1")
    prompt_condition = os.getenv("PROMPT_CONDITION", "PlannerWorker")

    # === 對齊環境變數（子模組用 os.environ 也讀得到）===
    os.environ["RUN_ID"] = session_id
    os.environ["SEED"] = str(seed)
    os.environ["TASK_ID"] = task_id
    os.environ["PROMPT_CONDITION"] = prompt_condition

    # 3. 使用 with tee_console_logs 包裹整个交互会话
    with tee_console_logs(run_id=session_id, log_dir=RUN_LOG_DIR, also_console=True) as log_paths:
        # 在 tee 启动后才打印，这样这些信息也会被记录到文件
        print(f"[System] STDOUT/STDERR logging to: {log_paths['stdout_path']}")
        print("輸入你的問題；指令：:reset | :save | :quit\n")

        # 4. 构建图和初始状态
        graph = build_team_graph()
        # state: Dict[str, Any] = {
        #     "messages": [],
        #     "blackboard": {},
        #     "tool_events": [],
        #     "violations": [],
        #     "pdf_dir": PDF_DOCS_PATH,
        #     "db_url": SQLITE_DB_PATH,
        #     "run_id": session_id,  # 先放進 state
        #     "policy": args.policy,
        #     "turn_counter": 0,
        # }
        state: Dict[str, Any] = {
            "messages": [],
            "blackboard": {},
            "tool_events": [],
            "violations": [],
            "pdf_dir": PDF_DOCS_PATH,
            "db_url": SQLITE_DB_PATH,
            "run_id": session_id,
            "policy": args.policy,
            "turn_counter": 0,
            "seed": seed,
            "task_id": task_id,
            "prompt_condition": prompt_condition,
        }
        ensure_run_id(state)  # 這行會把 os.environ["RUN_ID"] 也同步成 state["run_id"]
        init_metrics(state)
        _init_run_logger_from_cli(state, args)

        # 7) ★ 把 meta 記入 RunLogger（就加在這裡！）
        rl = get_run_logger()
        try:
            rl.data = rl.data if hasattr(rl, "data") else {}
            rl.data.setdefault("meta", {})
            rl.data["meta"].update({
                "run_id": state["run_id"],
                "task_id": state["task_id"],
                "seed": state["seed"],
                "prompt_condition": state["prompt_condition"],
            })
        except Exception:
            pass

        print(f"[DEBUG] RUN_ID={state['run_id']}  TASK_ID={state['task_id']}  "
              f"SEED={state['seed']}  PROMPT={state['prompt_condition']}")

        # 顯示 system prompt token 估算
        try:
            from context_assembler import DynamicContextAssembler
            _asm = DynamicContextAssembler()
            for _ag in ("Supervisor", "ME", "DE", "DS"):
                _sp = _asm.assemble_system_prompt(_ag)
                _tok = len(_sp) // 4
                print(f"[System prompt tokens] {_ag}: ~{_tok}")
        except Exception:
            pass

        begin_run(
            state,
            task_id=os.getenv("TASK_ID", "Unknown"),
            prompt_condition=os.getenv("PROMPT_CONDITION", "Unknown"),
            protocol_version=os.getenv("PROTOCOL_VERSION", "v1"),
            router_policy=state.get("policy", "free"),
            model_name=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
            temperature=float(os.getenv("GEMINI_TEMP", "0.25")),
            top_p=float(os.getenv("GEMINI_TOP_P", "1.0")),
            max_tokens=int(os.getenv("GEMINI_MAX_TOK", "8192") or 8192),
            seed=int(os.getenv("SEED", "42")),
            dataset_version=os.getenv("DATASET_VERSION", "TEP_Harvard_v1"),
        )
        emit_run_meta(state, pdf_dir=PDF_DOCS_PATH, db_url=SQLITE_DB_PATH)
        print(f"[DEBUG] chat_cli RUN_ID -> {state['run_id']}")

        # === Run 級 metadata：一次性寫入（可讓 ETL/分析知道這個 run 的自變項與環境） ===
        begin_run(
            state,
            task_id=os.getenv("TASK_ID", "Unknown"),
            prompt_condition=os.getenv("PROMPT_CONDITION", "Unknown"),
            protocol_version=os.getenv("PROTOCOL_VERSION", "v1"),
            router_policy=state.get("policy", "free"),
            model_name=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
            temperature=float(os.getenv("GEMINI_TEMP", "0.25")),
            top_p=float(os.getenv("GEMINI_TOP_P", "1.0")),
            max_tokens=int(os.getenv("GEMINI_MAX_TOK", "8192") or 8192),
            seed=int(os.getenv("SEED", "42")),
            dataset_version=os.getenv("DATASET_VERSION", "TEP_Harvard_v1"),
        )
        # 你也可以把路徑等輔助資訊寫進 meta（非必填）
        emit_run_meta(
            state,
            pdf_dir=PDF_DOCS_PATH,
            db_url=SQLITE_DB_PATH,
        )

        # 5. 主循环，增加了 try...finally 来确保日志保存
        try:
            while True:
                try:
                    # user = input("\n你 > ").strip()
                    user = _read_user_block()
                except EOFError:
                    print("\n再見！"); break

                if not user: continue
                if user == ":quit": print("再見！"); break
                if user == ":reset":
                    state = {
                        "messages": [],
                        "blackboard": {},
                        "tool_events": [],
                        "violations": [],
                        "pdf_dir": state["pdf_dir"],
                        "db_url": state["db_url"],
                        "run_id": state["run_id"],  # ← 沿用原本的
                        "policy": args.policy,
                        "turn_counter": 0,
                    }
                    ensure_run_id(state)  # 再同步一次（保險）
                    print(f"[System] 已重置會話與黑板（RUN_ID={state['run_id']}）。")
                    continue
                if user == ":save":
                    path = _save_session(session_id, state, tag="manual")
                    print(f"[System] 已存檔 -> {path}")
                    continue

                state["messages"].append(HumanMessage(content=user))
                state["turn_counter"] = 0

                # 内层循环，处理一个问题的多轮交互
                while state["turn_counter"] < 15:
                    state["turn_counter"] += 1
                    print(f"\n{'=' * 20} [STARTING TURN #{state['turn_counter']}] {'=' * 20}")

                    out_state = graph.invoke(state, {"recursion_limit": 60})
                    #
                    try:
                        final_text = ""
                        msgs = (out_state.get("messages") or state.get("messages") or [])
                        if isinstance(msgs, list) and msgs:
                            last = msgs[-1]
                            if isinstance(last, dict):
                                final_text = last.get("content", "") or last.get("text", "")
                            elif isinstance(last, str):
                                final_text = last
                        update_me_citation_metrics(state, answer_text=final_text)
                    except Exception:
                        pass

                    #
                    state.update(out_state or {})

                    last_msg = state["messages"][-1]
                    if isinstance(last_msg, AIMessage):
                        if (last_msg.tool_calls and last_msg.tool_calls[0]['name'] == 'final_answer') or (
                        not last_msg.tool_calls):
                            print(f"\n{'=' * 20} [TURN ENDED - Awaiting next input] {'=' * 20}")
                            _print_last(state)
                            # 在 while 迴圈裡，每回合 break 前：_print_last(state) 之後加
                            _print_recent_tool_events(state, limit=12)
                            _print_blackboard_summary(state)
                            # usage summary
                            try:
                                m = state.get("metrics", {})
                                tokens_in = m.get("tokens_in_total", 0)
                                tokens_out = m.get("tokens_out_total", 0)
                                latency = m.get("llm_latency_ms_sum", 0.0)
                                cache_hits = m.get("cache_hits", 0)
                                print(f"[Usage] tokens_in={tokens_in} tokens_out={tokens_out} "
                                      f"llm_latency={latency:.0f}ms cache_hits={cache_hits}")
                                from run_logger import _compute_cost_usd
                                cost = _compute_cost_usd(tokens_in, tokens_out)
                                if cost is not None:
                                    print(f"[Cost] ${cost:.4f}  (in={tokens_in:,} × $1.25/M  out={tokens_out:,} × $10.00/M)")
                                else:
                                    print("[Cost] no token data — HarnessCallback not triggered or no real API call")
                                if m.get("judge_triggered"):
                                    fg = m.get("judge_factual_grounding", "?")
                                    cp = m.get("judge_completeness", "?")
                                    co = m.get("judge_coherence", "?")
                                    print(f"[Judge] Factual:{fg}/3  Complete:{cp}/3  Coherent:{co}/3")
                            except Exception:
                                pass
                            _save_session(session_id, state, tag=f"turn_{state['turn_counter']}_end")
                            break

                if state["turn_counter"] >= 15:
                    print("\n[System WARNING] Reached maximum turn limit for this question.")

        except KeyboardInterrupt:
            print("\n[System] 侦测到手动中断 (Ctrl+C)...")
        except Exception:
            print("\n[Error] 程式意外崩潰。")
            # 打印堆栈信息到 stderr，它将被 tee 捕获
            traceback.print_exc()
        finally:
            try:
                finalize_metrics(state, ds_verdict="AUTO", ds_reason=None, final_answer_obj=None)
            except Exception:
                pass
            _finalize_run_logger(state)

            # === Outcome & 結束時間：把成功分數與成本彙總寫檔（供主模型與前沿分析） ===
            try:
                # 1) 估算 success_score（優先用 metrics；沒有就用啟發式落地）
                success_score = None
                try:
                    success_score = float((state.get("metrics") or {}).get("success_score"))
                except Exception:
                    success_score = None

                if success_score is None:
                    # 簡易啟發式：若最後一則 Supervisor 有 final answer 或長度>0，就給 1.0；否則 0.0
                    final_text = ""
                    msgs = state.get("messages", [])
                    if isinstance(msgs, list) and msgs:
                        last = msgs[-1]
                        if hasattr(last, "content"):
                            final_text = (last.content or "").strip()
                        elif isinstance(last, dict):
                            final_text = (last.get("content") or last.get("text") or "").strip()
                        elif isinstance(last, str):
                            final_text = last.strip()
                    success_score = 1.0 if final_text else 0.0

                # 2) 成本彙總：turns / messages / tool_calls（tool_calls 先用 legacy 計數作為 fallback）
                turns = int(state.get("turn_counter") or 0)
                # 訊息數：人話 + 模型回覆 + 工具回覆（粗略）

                messages = sum(1 for m in state.get("messages", []) if
                               isinstance(m, BaseMessage) or isinstance(m, dict) or isinstance(m, str))
                # 工具呼叫數：若你已全面改用 note_tool_call，可在 ETL 讀 events.jsonl 計；這裡先以 legacy 為主
                tool_calls = len(state.get("tool_events", []))

                emit_outcome(
                    state=state,
                    success_score=float(success_score),
                    notes="CLI session outcome (auto)",
                    turns=turns,
                    messages=messages,
                    tool_calls=tool_calls,
                )
            except Exception as e:
                print(f"[WARN] emit_outcome failed: {e}")

            # 3) 結束時間
            try:
                end_run(state)
            except Exception:
                pass
            print("[System] 正在储存最终会话 JSON 状态...")
            path = _save_session(session_id, state, tag="final_interrupt")
            print(f"[System] JSON 状态已成功储存至: {path}")
            print(f"[System] 完整的 stdout/stderr 日志已保存在 '{RUN_LOG_DIR}' 文件夹中。")


if __name__ == "__main__":
    main()

