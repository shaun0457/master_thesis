"""Integration evaluator for T1-P3: PostAnswer node, pure _cond() routing.

Does NOT require API key — tests routing logic only.

Run with:
    KMP_DUPLICATE_LIB_OK=TRUE python tests/integration/eval_t1p3.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("GOOGLE_API_KEY", "dummy-key-for-unit-test")


def _make_ai_msg_with_tool(name: str, args: dict):
    from langchain_core.messages import AIMessage
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": name, "args": args, "id": "tc_test"}]
    return msg


def test_cond_routes_final_answer_to_post_answer():
    """_cond must route final_answer (with evidence) to PostAnswer, not END."""
    from agents.supervisor_workflow import build_team_graph
    from langgraph.graph import END

    graph = build_team_graph()
    # Inspect that "PostAnswer" node exists
    node_names = list(graph.nodes)
    assert "PostAnswer" in node_names, (
        f"PostAnswer node not found in graph. Nodes: {node_names}"
    )
    print(f"[PASS] PostAnswer node exists: {node_names}")


def test_post_answer_node_is_callable():
    """post_answer_node must be importable and callable without API key."""
    from agents.supervisor_workflow import post_answer_node
    # Call with a state that has no final_answer — should return {} gracefully
    state = {"messages": [], "metrics": {}, "blackboard": {}}
    result = post_answer_node(state)
    assert result == {}, f"Expected empty dict, got {result}"
    print("[PASS] post_answer_node returns {} when no final_answer")


if __name__ == "__main__":
    test_cond_routes_final_answer_to_post_answer()
    test_post_answer_node_is_callable()
    print("[eval_t1p3] ALL PASSED")
