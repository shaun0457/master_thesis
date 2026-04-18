# mas/runtime/loop.py
"""
Runtime Execution Loop for O-MAS Multi-Agent System Experiments.

This module implements the core orchestration logic for running multi-agent
collaboration experiments. It coordinates agent interactions through a
turn-based execution model with blackboard-mediated communication.

Key Components:
    - Agent turn management and sequencing
    - Router-based message validation and routing
    - Blackboard I/O for shared memory communication
    - Event logging for process metric extraction
    - Termination condition detection

Architecture Overview:
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │  Supervisor │────▶│   Router    │────▶│  Blackboard │
    └─────────────┘     └─────────────┘     └─────────────┘
           │                   │                   │
           ▼                   ▼                   ▼
    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
    │  DE/DS/ME   │────▶│ Event Log   │────▶│  Metrics    │
    └─────────────┘     └─────────────┘     └─────────────┘

Protocol Support:
    - neutral: Baseline with minimal coordination rules
    - planner_to_worker: Hierarchical task delegation
    - debate: Adversarial argumentation with resolution
    - delphi: Iterative consensus through anonymous feedback

Usage:
    python -m mas.runtime.loop --query queries/task.md --protocol debate

Author: Cheng-Ting Chen
Thesis: Observable Multi-Agent Systems (O-MAS)
"""

import os
import re
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parents[2]))

from agents import SupervisorAgent, DataEngineerAgent, DataScientistAgent, MachineExpertAgent
from mas.logging.event_writer import write_turn, write_bb_write, write_read
from mas.core.router import Router
from mas.blackboard.store import BlackboardStore


def run_experiment(
    protocol: str,
    query_path: Path,
    run_id: str,
    seed: int,
    model_cfg: Dict[str, Any],
    max_turns: int = 20
) -> Dict[str, Any]:
    """
    Execute a single MAS experiment run with full event logging.

    This function orchestrates one complete experimental run, managing the
    lifecycle from initialization through termination. All agent interactions
    are logged for subsequent metric extraction and analysis.

    Execution Flow:
        1. Initialize blackboard storage for this run
        2. Initialize router with protocol-specific rules
        3. Create agent instances with protocol-specific prompts
        4. Load task query from file
        5. Execute turn loop until completion or timeout
        6. Generate final output and summary

    Args:
        protocol: Collaboration protocol identifier. One of:
            - 'neutral': Minimal coordination, agents self-organize
            - 'planner_to_worker': Supervisor plans, workers execute
            - 'debate': Adversarial discussion with judge resolution
            - 'delphi': Anonymous iterative consensus building
        query_path: Path to the task description file (Markdown format)
        run_id: Unique identifier for this run (e.g., 'debate-s42-20241115')
        seed: Random seed for reproducibility (affects LLM sampling)
        model_cfg: Model configuration dictionary containing:
            - model_name: LLM model identifier (e.g., 'gemini-2.5-pro')
            - temperature: Sampling temperature (0.0-1.0)
        max_turns: Maximum turns before forced termination (default: 20)

    Returns:
        dict: Run summary containing:
            - run_id: Echo of input run_id
            - protocol: Echo of input protocol
            - seed: Echo of input seed
            - turns: Actual number of turns executed
            - completed: Boolean indicating normal completion
            - final_owner: Last active agent role
            - violations: Count of protocol violations detected
            - timestamp: ISO format completion timestamp

    Side Effects:
        - Creates directory: data/blackboard/{run_id}/
        - Creates directory: data/runs/{run_id}/
        - Writes: turn_log.jsonl (all turn events)
        - Writes: bb_writes.jsonl (blackboard write events)
        - Writes: bb_reads.jsonl (blackboard read events)
        - Writes: final_output.txt (extracted final report)
        - Writes: stdout.txt (complete execution log)

    Raises:
        FileNotFoundError: If query_path does not exist
        ValueError: If protocol is not recognized

    Example:
        >>> summary = run_experiment(
        ...     protocol='debate',
        ...     query_path=Path('queries/diagnosis_task.md'),
        ...     run_id='debate-s42-20241115-143022',
        ...     seed=42,
        ...     model_cfg={'model_name': 'gemini-2.5-pro', 'temperature': 0.25},
        ...     max_turns=20
        ... )
        >>> print(f"Completed: {summary['completed']} in {summary['turns']} turns")
    """
    print(f"[RUN] Starting experiment: {run_id}")
    print(f"  Protocol: {protocol}")
    print(f"  Seed: {seed}")
    print(f"  Max turns: {max_turns}")
    print()

    # =========================================================================
    # PHASE 1: INITIALIZATION
    # =========================================================================

    # 1.1 Initialize blackboard storage
    # The blackboard provides shared memory for agent communication.
    # Each run gets isolated storage under data/blackboard/{run_id}/
    bb_root = Path(os.getenv("BB_ROOT", "data/blackboard"))
    bb_store = BlackboardStore(root=bb_root, run_id=run_id)
    print(f"[OK] Blackboard initialized: {bb_store.run_root}")

    # 1.2 Initialize router
    # The router validates messages against protocol rules and determines
    # which agent should act next. It also tracks protocol violations.
    router = Router(bb_store=bb_store, protocol=protocol, run_id=run_id)
    print(f"[OK] Router initialized: {protocol}")

    # 1.3 Initialize agents
    # Each agent receives:
    #   - bb_store: Reference to blackboard for read/write operations
    #   - router: Reference to router for message submission
    #   - protocol: Protocol name to load appropriate prompt templates
    #   - model_cfg: LLM configuration (model name, temperature)
    agents = {
        "supervisor": SupervisorAgent(
            bb_store,
            router,
            protocol=protocol,
            **model_cfg),
        "de": DataEngineerAgent(
            bb_store,
            router,
            protocol=protocol,
            **model_cfg),
        "ds": DataScientistAgent(
            bb_store,
            router,
            protocol=protocol,
            **model_cfg),
        "me": MachineExpertAgent(
            bb_store,
            router,
            protocol=protocol,
            **model_cfg)}
    print(f"[OK] Agents initialized: {list(agents.keys())}")

    # 1.4 Load query/task description
    with open(query_path, 'r', encoding='utf-8') as f:
        query = f.read()
    print(f"[OK] Query loaded: {query_path}")
    print()

    # 1.5 Initialize execution context
    # The context maintains state across turns:
    #   - history: List of all turn messages for context building
    #   - active_owner: Current agent responsible for next action
    #   - completed: Flag set when task is finished
    #   - write_registry: Maps bb:// URIs to their write metadata for reads
    context = {
        "run_id": run_id,
        "protocol": protocol,
        "query": query,
        "history": [],
        "active_owner": "supervisor",  # Supervisor always starts
        "completed": False,
        "write_registry": {}  # Track bb://uri -> write_event mapping
    }

    # =========================================================================
    # PHASE 2: MAIN EXECUTION LOOP
    # =========================================================================

    turn = 0
    while turn < max_turns and not context["completed"]:
        print(f"--- Turn {turn} (Owner: {context['active_owner']}) ---")

        # Get the agent whose turn it is
        agent = agents[context["active_owner"]]

        try:
            # -----------------------------------------------------------------
            # STEP 2.1: Process pending blackboard reads
            # -----------------------------------------------------------------
            # Agents may need to read artifacts written by others in previous
            # turns. The pending_reads list tracks URIs that need to be fetched.
            bb_refs_to_read = context.get("pending_reads", [])
            read_events = []
            for ref_uri in bb_refs_to_read:
                try:
                    content = agent.read_from_blackboard(ref_uri)

                    # Build complete read event with provenance information
                    # This links the read back to the original write event
                    write_info = context["write_registry"].get(ref_uri, {})

                    read_event = {
                        "schema": "run.read.v1",
                        "schema_version": "1.0",
                        "run_id": run_id,
                        "read_id": f"read-{agent.role}-t{turn}-{ref_uri.split('/')[-1]}",
                        "turn_index": turn,
                        "topic_id": write_info.get("topic_id", "system"),
                        "protocol": protocol,
                        "reader_role": agent.role,
                        "reader_agent_id": f"agents/{agent.role}",
                        "artifact": ref_uri,
                        "artifact_kind": write_info.get("artifact_kind", "text"),
                        "read_purpose": "planning",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        # Link to original write for reuse/orphan calculation
                        "write_ref": {
                            "event_id": write_info.get("write_id", "system-init"),
                            "turn_index": write_info.get("turn_index", 0),
                            "writer_role": write_info.get("writer_role", "router"),
                            "ts": write_info.get("ts", datetime.now(timezone.utc).isoformat())
                        },
                        "provenance": {
                            "code_commit": os.getenv("GIT_COMMIT", "0000000"),
                            "agent_version": "1.0.0"
                        }
                    }

                    read_events.append(read_event)
                    print(f"[BB Read] {agent.role} read {ref_uri}")
                except Exception as e:
                    print(f"[BB Read Error] Failed to read {ref_uri}: {e}")

                    traceback.print_exc()

            # -----------------------------------------------------------------
            # STEP 2.2: Agent action with retry logic
            # -----------------------------------------------------------------
            # The agent generates its response based on context.
            # Transient API failures (rate limits, timeouts) trigger retries.
            max_retries = 2
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    # Agent.act() calls the LLM and returns a structured message
                    turn_message = agent.act(context)

                    # Print full message for complete audit trail
                    print(f"[Agent] {agent.role}:")
                    print(f"--- BEGIN MESSAGE ---")
                    print(turn_message['message'])
                    print(f"--- END MESSAGE ---")
                    print()
                    break  # Success - exit retry loop
                except Exception as act_error:
                    last_error = act_error
                    if attempt < max_retries:

                        print(f"[RETRY] Agent {agent.role} failed (attempt {attempt + 1}/{max_retries + 1}): {act_error}")
                        print(f"[RETRY] Retrying in 2 seconds...")
                        time.sleep(2)
                    else:
                        print(f"[FATAL] Agent {agent.role} failed after {max_retries + 1} attempts")
                        raise

            # -----------------------------------------------------------------
            # STEP 2.3: Route message through protocol validator
            # -----------------------------------------------------------------
            # The router checks if the message conforms to protocol rules
            # and determines the next agent to act.
            routing_result = router.route(turn_message)
            print(f"[Router] Status: {routing_result['status']}")

            if routing_result["violations"]:
                print(f"[Router] Violations: {routing_result['violations']}")

            # -----------------------------------------------------------------
            # STEP 2.4: Handle blackboard writes
            # -----------------------------------------------------------------
            # If the agent produced an artifact (analysis, plan, etc.),
            # write it to the blackboard for other agents to access.
            write_events = []
            if turn_message.get("metrics_trace", {}).get("write_event", False):
                intent = turn_message.get("intent")
                task_id = turn_message.get("action", {}).get("task_id", f"task-{turn}")

                content = {
                    "message": turn_message.get("message"),
                    "intent": intent,
                    "role": agent.role,
                    "turn": turn,
                    "timestamp": turn_message.get("ts")
                }

                try:
                    bb_uri, write_event = agent.write_to_blackboard(
                        intent=intent,
                        content=content,
                        task_id=task_id
                    )

                    write_event["refs_out"] = turn_message.get("blackboard_refs", [])
                    write_events.append(write_event)

                    # Register write for future read tracking
                    # This enables reuse/orphan metric calculation
                    context["write_registry"][bb_uri] = {
                        "write_id": write_event["write_id"],
                        "turn_index": write_event["turn_index"],
                        "writer_role": write_event["writer_role"],
                        "topic_id": write_event["topic_id"],
                        "artifact_kind": write_event["artifact_kind"],
                        "ts": write_event["ts"]
                    }

                    if bb_uri not in turn_message["blackboard_refs"]:
                        turn_message["blackboard_refs"].append(bb_uri)

                    print(f"[BB Write] {agent.role} wrote {bb_uri}")

                except Exception as e:
                    print(f"[BB Write Error] Failed to write: {e}")

                    traceback.print_exc()

            # -----------------------------------------------------------------
            # STEP 2.5: Persist events to log files
            # -----------------------------------------------------------------
            # All events are written to JSONL files for post-hoc analysis
            write_turn(bb_store, turn_message)

            for read_event in read_events:
                write_read(bb_store, read_event)

            for write_event in write_events:
                write_bb_write(bb_store, write_event)

            # -----------------------------------------------------------------
            # STEP 2.6: Update context for next turn
            # -----------------------------------------------------------------
            context["history"].append(turn_message)
            context["pending_reads"] = turn_message.get("blackboard_refs", [])

            # -----------------------------------------------------------------
            # STEP 2.7: Check termination conditions
            # -----------------------------------------------------------------
            # Run completes when supervisor reports with no target (final report)
            if turn_message["intent"] in ["report", "consensus"]:
                if turn_message["action"]["target"] is None:
                    print("[COMPLETE] Run finished")
                    context["completed"] = True
                    break

            # -----------------------------------------------------------------
            # STEP 2.8: Determine next agent
            # -----------------------------------------------------------------
            next_owner = routing_result.get("next_owner")
            if next_owner:
                context["active_owner"] = next_owner.lower()
            else:
                context["active_owner"] = "supervisor"

            turn += 1
            print()

        except Exception as e:
            # -----------------------------------------------------------------
            # ERROR HANDLING: Log and continue or abort
            # -----------------------------------------------------------------
            error_msg = f"Turn {turn} failed: {e}"
            print(f"[ERROR] {error_msg}")
            tb = traceback.format_exc()
            print(tb)

            # Write detailed error log for post-mortem analysis
            try:
                error_file = bb_store.run_path / "error.log"
                with open(error_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{'=' * 60}\n")
                    f.write(f"[{datetime.now(timezone.utc).isoformat()}]\n")
                    f.write(f"Turn: {turn}\n")
                    f.write(f"Active Owner: {context.get('active_owner', 'unknown')}\n")
                    f.write(f"Error: {error_msg}\n")
                    f.write(f"Traceback:\n{tb}\n")
                    f.write(f"{'=' * 60}\n")
            except Exception as write_err:
                print(f"[WARNING] Could not write error.log: {write_err}")

            break

    # =========================================================================
    # PHASE 3: FINALIZATION
    # =========================================================================

    # Generate final_output.txt for grading and analysis
    # This extracts the final report from either:
    #   1. Normal completion: Last supervisor message
    #   2. Timeout: Forced summary generation
    print()
    print("[FINALIZE] Generating final_output.txt...")

    try:
        runs_root = os.getenv("RUNS_ROOT", "data/runs")
        run_path = Path(runs_root) / run_id
        stdout_path = run_path / "stdout.txt"
        final_output_path = run_path / "final_output.txt"

        final_content = None
        generation_method = None

        if context["completed"]:
            # Normal completion - extract last supervisor turn from history
            print("[INFO] Run completed normally, extracting from history...")

            last_supervisor = next(
                (t for t in reversed(context["history"]) if t.get("role") == "supervisor"),
                None,
            )
            if last_supervisor:
                final_content = last_supervisor.get("message", "").strip()
                generation_method = "extracted_from_history_supervisor"
                print(f"[OK] Extracted final message from supervisor ({len(final_content)} chars)")
            elif stdout_path.exists():
                # Fallback to stdout parsing
                with open(stdout_path, 'r', encoding='utf-8', errors='ignore') as f:
                    stdout_content = f.read()

                pattern = r'\[Agent\] (\w+):\n--- BEGIN MESSAGE ---\n(.*?)\n--- END MESSAGE ---'
                matches = re.findall(pattern, stdout_content, re.DOTALL)

                if matches:
                    last_role, last_message = matches[-1]
                    final_content = last_message.strip()
                    generation_method = f"extracted_from_stdout_{last_role}"
                    print(f"[OK] Extracted final message from {last_role} ({len(final_content)} chars)")

        else:
            # Timeout - generate forced summary
            print("[WARNING] Run reached max_turns without completion")
            print("[INFO] Generating forced summary from supervisor...")

            summary_context = {
                "run_id": run_id,
                "protocol": protocol,
                "query": context.get("query", ""),
                "turns_completed": turn,
                "max_turns": max_turns,
                "history": context["history"],
                "reason": "max_turns_reached"
            }

            # Build summary of recent activity
            history_summary = []
            for i, turn_msg in enumerate(context["history"][-10:], 1):
                role = turn_msg.get("role", "unknown")
                intent = turn_msg.get("intent", "unknown")
                msg_preview = turn_msg.get("message", "")[:200]
                history_summary.append(f"Turn {turn_msg.get('turn_index', '?')} ({role}, {intent}): {msg_preview}...")

            summary_prompt = f"""The team has reached the maximum turn limit ({max_turns} turns) without completing the task.

Please provide a summary of what was accomplished and what remains to be done.

**Original Task:**
{context.get('query', 'N/A')[:500]}

**Recent Activity (last 10 turns):**
{chr(10).join(history_summary)}

**Your task:**
Generate a summary report covering:
1. What the team has accomplished so far
2. Key findings or insights discovered
3. What remains incomplete
4. Recommendations for next steps

Format as a professional diagnostic report.
"""

            try:
                supervisor = agents.get("supervisor")
                if supervisor:
                    forced_summary_context = {
                        "run_id": run_id,
                        "protocol": protocol,
                        "query": summary_prompt,
                        "history": context["history"],
                        "active_owner": "supervisor",
                        "completed": False,
                        "write_registry": context.get("write_registry", {})
                    }

                    print("[INFO] Calling supervisor.act() for forced summary...")
                    summary_turn = supervisor.act(forced_summary_context)

                    final_content = summary_turn.get("message", "")
                    generation_method = "forced_summary_supervisor"

                    print(f"\n[FORCED SUMMARY] Generated by supervisor:")
                    print(f"--- BEGIN MESSAGE ---")
                    print(final_content)
                    print(f"--- END MESSAGE ---")
                    print()

                    print(f"[OK] Generated forced summary ({len(final_content)} chars)")

            except Exception as summary_error:
                print(f"[ERROR] Failed to generate forced summary: {summary_error}")
                traceback.print_exc()

                # Fallback: Concatenate recent messages
                print("[WARNING] Using fallback: concatenating recent messages...")

                fallback_parts = [
                    f"# Incomplete Run Summary - {run_id}",
                    f"",
                    f"**Status:** Run reached maximum turn limit ({turn}/{max_turns}) without completion",
                    f"**Protocol:** {protocol}",
                    f"",
                    f"## Work Completed:",
                    f""
                ]

                for turn_msg in context["history"][-5:]:
                    role = turn_msg.get("role", "unknown")
                    intent = turn_msg.get("intent", "unknown")
                    msg = turn_msg.get("message", "")
                    if msg and len(msg) > 100:
                        fallback_parts.append(f"### {role.upper()} (Turn {turn_msg.get('turn_index', '?')}):")
                        fallback_parts.append(msg[:1000])
                        fallback_parts.append("")

                final_content = "\n".join(fallback_parts)
                generation_method = "fallback_concatenated"

        # Write final_output.txt with metadata header
        if final_content and len(final_content) > 50:
            with open(final_output_path, 'w', encoding='utf-8') as f:
                f.write(f"# Run: {run_id}\n")
                f.write(f"# Protocol: {protocol}\n")
                f.write(f"# Turns: {turn}/{max_turns}\n")
                f.write(f"# Completed: {context['completed']}\n")
                f.write(f"# Generation Method: {generation_method}\n")
                f.write(f"\n---\n\n")
                f.write(final_content)

            print(f"[OK] Generated: {final_output_path}")
            print(f"[OK] Method: {generation_method}")

        else:
            print(f"[ERROR] Could not generate final_output.txt")

            placeholder = f"""# Run: {run_id}

**Protocol:** {protocol}
**Turns:** {turn}/{max_turns}
**Completed:** {context['completed']}

**Error:** Failed to extract or generate final report.

Please review stdout.txt manually.
"""
            with open(final_output_path, 'w', encoding='utf-8') as f:
                f.write(placeholder)

    except Exception as e:
        print(f"[ERROR] Final output generation failed: {e}")
        traceback.print_exc()

    # =========================================================================
    # PHASE 4: GENERATE SUMMARY
    # =========================================================================

    summary = {
        "run_id": run_id,
        "protocol": protocol,
        "seed": seed,
        "turns": turn,
        "completed": context["completed"],
        "final_owner": context["active_owner"],
        "violations": router.violation_count,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    print()
    print("=" * 60)
    print(f"[SUMMARY] Run: {run_id}")
    print(f"  Turns: {turn}/{max_turns}")
    print(f"  Completed: {context['completed']}")
    print(f"  Violations: {router.violation_count}")
    print("=" * 60)

    return summary


def main():
    """
    Command-line interface for running single experiments.

    Primarily used for testing and debugging individual runs.
    For batch experiments, use cli/run_experiment.py instead.

    Usage:
        python -m mas.runtime.loop --query queries/task.md --protocol debate
        python -m mas.runtime.loop --query queries/task.md --protocol neutral --max-turns 30
    """
    import argparse

    parser = argparse.ArgumentParser(description="Run a single MAS experiment")
    parser.add_argument(
        "--query",
        type=Path,
        required=True,
        help="Query file path")
    parser.add_argument(
        "--protocol",
        choices=[
            "neutral",
            "planner_to_worker",
            "debate",
            "delphi"],
        required=True)
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run ID (auto-generated if not provided)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-turns", type=int, default=20, help="Max turns")

    args = parser.parse_args()

    # Generate run_id if not provided
    if not args.run_id:
        from datetime import datetime
        args.run_id = f"test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Model configuration from environment
    model_cfg = {
        "model_name": os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
        "temperature": float(os.getenv("GEMINI_TEMP", "0.25"))
    }

    # Execute experiment
    summary = run_experiment(
        protocol=args.protocol,
        query_path=args.query,
        run_id=args.run_id,
        seed=args.seed,
        model_cfg=model_cfg,
        max_turns=args.max_turns
    )

    return 0 if summary["completed"] else 1


if __name__ == "__main__":
    sys.exit(main())
