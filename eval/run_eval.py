"""Golden Dataset Eval Pipeline — T3-P10.

Runs each golden QA against the MAS and records:
  - answer text
  - keyword_hits / keyword_hit_rate
  - agent_path_hit (did expected agent(s) respond?)
  - latency_ms
  - ds_verdict (for DS-path questions)
  - me_citation_coverage (from metrics)

Usage:
    # Dry-run (no API key needed, uses stub answers):
    python eval/run_eval.py --dry-run

    # Real run (needs GOOGLE_API_KEY):
    GOOGLE_API_KEY=<key> python eval/run_eval.py
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

GOLDEN_QA_PATH = Path(__file__).parent / "golden_qa.json"
RESULTS_PATH   = Path(__file__).parent / "results.json"


def _keyword_hits(answer: str, keywords: list[str]) -> int:
    a = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in a)


def _run_dry(item: dict) -> dict:
    """Return a stub answer that satisfies keyword requirements for smoke-testing."""
    agent = item["agent_path"][0]
    kws = item["expected_keywords"]
    stub = f"[DRY-RUN] {agent} answer mentioning: {', '.join(kws[:3])}"
    return {
        "id": item["id"],
        "question": item["question"],
        "answer": stub,
        "keyword_hits": len(kws),
        "keyword_hit_rate": 1.0,
        "agent_path_hit": True,
        "latency_ms": 0,
        "ds_verdict": "ok" if agent == "DS" else None,
        "me_citation_coverage": 0.5 if agent == "ME" else None,
        "dry_run": True,
    }


def _run_real(item: dict) -> dict:
    """Run one QA against the live MAS graph."""
    import uuid
    os.environ.setdefault("RUN_ID", f"eval-{uuid.uuid4().hex[:8]}")
    os.environ.setdefault("TASK_ID", item["id"])

    from common import AgentState
    from supervisor_workflow import build_team_graph
    from langchain_core.messages import HumanMessage

    graph = build_team_graph()
    init_state: AgentState = {
        "messages": [HumanMessage(content=item["question"])],
        "metrics": {},
        "blackboard": {},
    }

    t0 = time.time()
    try:
        final_state = graph.invoke(init_state, config={"recursion_limit": 50})
        latency_ms = (time.time() - t0) * 1000

        # Extract answer: prefer final_answer tool_call args, fall back to AIMessage.content
        from langchain_core.messages import AIMessage
        answer = ""
        for msg in reversed(final_state.get("messages", [])):
            if isinstance(msg, AIMessage):
                for tc in (getattr(msg, "tool_calls", None) or []):
                    if tc.get("name") == "final_answer":
                        answer = tc.get("args", {}).get("answer", "")
                        break
                if answer:
                    break
                if msg.content:
                    c = msg.content
                    if isinstance(c, str):
                        answer = c
                    elif isinstance(c, list):
                        # Gemini content blocks: [{"type": "text", "text": "..."}]
                        answer = " ".join(
                            part.get("text", "") for part in c
                            if isinstance(part, dict)
                        )
                    else:
                        answer = str(c)
                    break

        metrics = final_state.get("metrics", {})
        hits = _keyword_hits(answer, item["expected_keywords"])
        hit_rate = hits / max(len(item["expected_keywords"]), 1)

        # agent_path_hit: check if expected agent's tool was called
        tool_events = final_state.get("tool_events", [])
        expected_agents = set(item.get("agent_path", []))
        agents_seen = {e.get("agent", "") for e in tool_events if isinstance(e, dict)}
        path_hit = bool(expected_agents & agents_seen) if expected_agents else True

        return {
            "id": item["id"],
            "question": item["question"],
            "answer": answer[:500],
            "keyword_hits": hits,
            "keyword_hit_rate": round(hit_rate, 3),
            "min_keyword_hits": item.get("min_keyword_hits", 1),
            "agent_path_hit": path_hit,
            "latency_ms": round(latency_ms),
            "ds_verdict": metrics.get("ds_verdict"),
            "me_citation_coverage": metrics.get("me_citation_coverage"),
            "dry_run": False,
        }
    except Exception as e:
        return {
            "id": item["id"],
            "question": item["question"],
            "answer": "",
            "error": f"{type(e).__name__}: {e}",
            "keyword_hits": 0,
            "keyword_hit_rate": 0.0,
            "agent_path_hit": False,
            "latency_ms": round((time.time() - t0) * 1000),
            "ds_verdict": None,
            "me_citation_coverage": None,
            "dry_run": False,
        }


def run_eval(dry_run: bool = False) -> list[dict]:
    golden = json.loads(GOLDEN_QA_PATH.read_text(encoding="utf-8"))
    results = []
    for item in golden:
        print(f"  [{item['id']}] {item['question'][:60]}...", end=" ", flush=True)
        result = _run_dry(item) if dry_run else _run_real(item)
        status = "PASS" if result["keyword_hit_rate"] >= (item.get("min_keyword_hits", 1) / max(len(item["expected_keywords"]), 1)) else "FAIL"
        print(status)
        results.append(result)

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults written to {RESULTS_PATH}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Use stub answers (no API key needed)")
    args = parser.parse_args()

    if not args.dry_run and not os.getenv("GOOGLE_API_KEY"):
        print("WARNING: GOOGLE_API_KEY not set. Use --dry-run for smoke test.")
        sys.exit(1)

    os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-dry-run")
    print(f"Running golden eval ({'dry-run' if args.dry_run else 'live'})...")
    results = run_eval(dry_run=args.dry_run)

    passed = sum(1 for r in results if r.get("keyword_hit_rate", 0) >= (r.get("min_keyword_hits", 1) / 3))
    print(f"\nSummary: {passed}/{len(results)} questions met keyword threshold")
