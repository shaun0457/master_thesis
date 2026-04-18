# agents/base.py
"""
Base Agent for O-MAS Multi-Agent System.

Provides shared LLM interaction, blackboard I/O, prompt loading,
and structured response parsing for all concrete agent roles.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import google.generativeai as genai


# Root of the prompts directory (two levels up from this file)
_PROMPTS_ROOT = Path(__file__).parents[1] / "prompts"

# intent → blackboard topic mapping
_INTENT_TO_TOPIC = {
    "analyze": "analysis",
    "report":  "reports",
    "data":    "datasets",
}


class BaseAgent:
    """
    Abstract base agent for O-MAS experiments.

    Subclasses inherit LLM calling, blackboard access, and prompt loading.
    Override `_build_prompt` to add role-specific context sections.

    Args:
        role: Canonical role name ("supervisor", "de", "ds", "me").
        bb_store: BlackboardStore instance for read/write operations.
        router: Router instance for message routing.
        protocol: Active collaboration protocol name.
        model_name: Gemini model identifier.
        temperature: LLM sampling temperature (0.0–1.0).
    """

    def __init__(
        self,
        role: str,
        bb_store,
        router,
        protocol: str,
        model_name: str = "gemini-2.5-pro",
        temperature: float = 0.25,
    ) -> None:
        self.role = role
        self.bb_store = bb_store
        self.router = router
        self.protocol = protocol
        self.model_name = model_name
        self.temperature = temperature

        # Configure Gemini client
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            genai.configure(api_key=api_key)

        self._model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=genai.GenerationConfig(temperature=temperature),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def act(self, context: dict) -> dict:
        """
        Generate a structured turn message from the current run context.

        Args:
            context: Run context dict (run_id, protocol, query, history, …).

        Returns:
            dict: Populated run.turn.v2 event dict.
        """
        prompt = self._build_prompt(context)
        turn_index = len(context.get("history", []))
        run_id = context.get("run_id", "unknown")

        t0 = time.time()
        response = self._model.generate_content(prompt)
        latency_ms = int((time.time() - t0) * 1000)

        raw_text = response.text or ""
        tokens = {
            "input":  getattr(getattr(response, "usage_metadata", None), "prompt_token_count", 0),
            "output": getattr(getattr(response, "usage_metadata", None), "candidates_token_count", 0),
        }

        return self._parse_response(raw_text, context, latency_ms, tokens)

    def read_from_blackboard(self, uri: str) -> Any:
        """
        Read an artifact from the blackboard.

        Args:
            uri: bb:// URI of the artifact.

        Returns:
            Parsed artifact (dict for JSON, dict with 'data' key for Parquet).
        """
        if uri.endswith(".parquet"):
            return self.bb_store.read_parquet(uri)
        return self.bb_store.read_json(uri)

    def write_to_blackboard(
        self,
        intent: str,
        content: dict,
        task_id: str,
    ) -> Tuple[str, dict]:
        """
        Write an artifact to the blackboard and return its URI and write event.

        Args:
            intent: Agent intent (determines topic namespace).
            content: Artifact payload to persist.
            task_id: Associated task identifier.

        Returns:
            Tuple of (bb_uri, write_event_dict).
        """
        topic = _INTENT_TO_TOPIC.get(intent, "artifacts")
        run_id = self.bb_store.run_id
        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = f"{self.role}_{task_id}_{ts_tag}.json"
        bb_uri = f"bb://{topic}/{filename}"

        self.bb_store.write_json(bb_uri, content)

        write_event = {
            "schema":        "bb.write.v1",
            "run_id":        run_id,
            "write_id":      f"write-{self.role}-{task_id}-{ts_tag}",
            "turn_index":    len(self.bb_store.run_id),  # placeholder; caller fills in
            "writer_role":   self.role,
            "topic_id":      topic,
            "artifact":      bb_uri,
            "artifact_kind": "json",
            "refs_out":      [],
            "ts":            datetime.now(timezone.utc).isoformat(),
        }

        return bb_uri, write_event

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, context: dict) -> str:
        """
        Assemble the full prompt for this agent's turn.

        Loads role system prompt and optional protocol overlay, then appends
        conversation history and current task query.

        Args:
            context: Run context dict.

        Returns:
            str: Full prompt string for the LLM.
        """
        parts = []

        # 1. Role system prompt
        role_file = _PROMPTS_ROOT / "roles" / f"{self.role}.md"
        if role_file.exists():
            parts.append(role_file.read_text(encoding="utf-8"))

        # 2. Protocol overlay (optional)
        proto_file = _PROMPTS_ROOT / "protocols" / self.protocol / f"{self.role}.md"
        if proto_file.exists():
            parts.append(proto_file.read_text(encoding="utf-8"))

        # 3. Task query
        query = context.get("query", "")
        if query:
            parts.append(f"\n# Current Task\n{query}")

        # 4. Conversation history (last 10 turns)
        history = context.get("history", [])[-10:]
        if history:
            hist_lines = ["\n# Conversation History"]
            for turn in history:
                r = turn.get("role", "?")
                m = turn.get("message", "")[:800]
                hist_lines.append(f"\n## {r.upper()}\n{m}")
            parts.append("\n".join(hist_lines))

        # 5. Output format instruction
        parts.append(
            "\n# Output Format\n"
            "Respond with a JSON block wrapped in ```json ... ``` containing:\n"
            '  "schema", "role", "turn_index", "intent", "message", "action", '
            '"blackboard_refs", "metrics_trace", "ts"\n'
            "Then you may add natural language explanation after the JSON block."
        )

        return "\n\n".join(parts)

    def _parse_response(
        self,
        text: str,
        context: dict,
        latency_ms: int,
        tokens: dict,
    ) -> dict:
        """
        Extract structured turn event from raw LLM output.

        Tries to find a ```json ... ``` block; falls back to wrapping the full
        text as a plain message if no valid JSON block is present.

        Args:
            text: Raw LLM response text.
            context: Run context for fallback field population.
            latency_ms: Measured LLM call latency.
            tokens: Dict with "input" and "output" token counts.

        Returns:
            dict: Populated run.turn.v2 event dict.
        """
        run_id = context.get("run_id", "unknown")
        turn_index = len(context.get("history", []))
        ts = datetime.now(timezone.utc).isoformat()

        # Try to extract JSON block
        parsed: Optional[dict] = None
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        if parsed is None:
            # Fallback: wrap full text as plain message
            parsed = {
                "intent":  "work",
                "message": text,
                "action":  {"target": None},
            }

        # Ensure required top-level fields are present
        parsed.setdefault("schema",         "run.turn.v2")
        parsed.setdefault("run_id",         run_id)
        parsed.setdefault("turn_index",     turn_index)
        parsed.setdefault("role",           self.role)
        parsed.setdefault("intent",         "work")
        parsed.setdefault("message",        text)
        parsed.setdefault("action",         {"target": None})
        parsed.setdefault("blackboard_refs", [])
        parsed.setdefault("ts",             ts)

        # Always overwrite provenance fields so they reflect actual execution
        parsed["role"]        = self.role
        parsed["run_id"]      = run_id
        parsed["turn_index"]  = turn_index
        parsed["ts"]          = ts

        # Attach runtime metrics
        parsed["metrics_trace"] = parsed.get("metrics_trace") or {}
        parsed["metrics_trace"].update({
            "latency_ms":    latency_ms,
            "tokens_input":  tokens.get("input",  0),
            "tokens_output": tokens.get("output", 0),
            "write_event":   bool(parsed.get("blackboard_refs")),
        })

        return parsed
