# mas/enrich/tdi.py
"""
TDI (Topic Drift Indicator) computation for X-MAS experiments.

Computes:
- similarity_s: Cosine similarity between goal and intent embeddings [-1, 1]
- drift_D: Drift measure D = 1-(s+1)/2 [0, 1]
"""

import os
import json
import hashlib
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()


def embed_text(text: str, model_name: str = "text-embedding-004") -> np.ndarray:
    """
    Generate embedding for text using Vertex AI.

    Args:
        text: Input text to embed
        model_name: Embedding model name

    Returns:
        np.ndarray: Embedding vector
    """
    import vertexai
    from vertexai.language_models import TextEmbeddingModel

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    vertexai.init(project=project, location=location)

    model = TextEmbeddingModel.from_pretrained(model_name)
    embeddings = model.get_embeddings([text])

    return np.array(embeddings[0].values)


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    Compute cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        float: Cosine similarity in range [-1, 1]
    """
    # Normalize vectors
    vec1_norm = vec1 / (np.linalg.norm(vec1) + 1e-10)
    vec2_norm = vec2 / (np.linalg.norm(vec2) + 1e-10)

    # Compute dot product
    similarity = np.dot(vec1_norm, vec2_norm)

    # Clip to valid range (numerical stability)
    return float(np.clip(similarity, -1.0, 1.0))


def compute_drift_from_similarity(similarity_s: float) -> float:
    """
    Compute drift measure D from similarity s.

    Formula: D = 1 - (s + 1) / 2

    Args:
        similarity_s: Cosine similarity in range [-1, 1]

    Returns:
        float: Drift measure in range [0, 1]
            - D = 0: perfect alignment (s = 1)
            - D = 1: maximum drift (s = -1)
    """
    drift_D = 1.0 - (similarity_s + 1.0) / 2.0
    return float(np.clip(drift_D, 0.0, 1.0))


def compute_tdi_for_turn(
    goal_text: str,
    intent_text: str,
    embed_model: str = "text-embedding-004",
    bb_root: Optional[Path] = None,
    run_id: Optional[str] = None,
    turn_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Compute TDI (Topic Drift Indicator) for a single turn.

    Args:
        goal_text: User goal text (initial task description)
        intent_text: Current turn's intent/message text
        embed_model: Embedding model name
        bb_root: Blackboard root path (for saving embeddings)
        run_id: Run identifier
        turn_id: Turn index

    Returns:
        dict: TDI metrics with structure:
        {
            "user_goal_ref": "bb://...",
            "intent_embed_ref": "bb://...",
            "similarity_s": float,  # [-1, 1]
            "drift_D": float,       # [0, 1]
            "embed_model": str
        }
    """
    # Compute embeddings
    goal_embedding = embed_text(goal_text, embed_model)
    intent_embedding = embed_text(intent_text, embed_model)

    # Compute similarity
    similarity_s = cosine_similarity(goal_embedding, intent_embedding)

    # Compute drift
    drift_D = compute_drift_from_similarity(similarity_s)

    # Save embeddings if bb_root provided
    goal_ref = "bb://goal_embedding"
    intent_ref = "bb://intent_embedding"

    if bb_root and run_id and turn_id is not None:
        bb_path = Path(bb_root) / run_id / "embeddings"
        bb_path.mkdir(parents=True, exist_ok=True)

        # Save goal embedding (once per run)
        goal_file = bb_path / "goal_embed.json"
        if not goal_file.exists():
            goal_data = {
                "schema": "embedding.vector.v1",
                "model": embed_model,
                "text_sha256": hashlib.sha256(goal_text.encode()).hexdigest(),
                "vector": goal_embedding.tolist(),
                "dim": len(goal_embedding),
                "norm_l2": float(np.linalg.norm(goal_embedding)),
                "source": {
                    "run_id": run_id,
                    "turn_id": None,
                    "kind": "goal",
                    "topic_id": None
                },
                "text_bytes": len(goal_text.encode()),
                "ts": None  # Will be filled by caller
            }
            with open(goal_file, 'w', encoding='utf-8') as f:
                json.dump(goal_data, f, indent=2)

        # Save intent embedding (per turn)
        intent_file = bb_path / f"intent_t{turn_id}.json"
        intent_data = {
            "schema": "embedding.vector.v1",
            "model": embed_model,
            "text_sha256": hashlib.sha256(intent_text.encode()).hexdigest(),
            "vector": intent_embedding.tolist(),
            "dim": len(intent_embedding),
            "norm_l2": float(np.linalg.norm(intent_embedding)),
            "source": {
                "run_id": run_id,
                "turn_id": turn_id,
                "kind": "intent",
                "topic_id": None
            },
            "text_bytes": len(intent_text.encode()),
            "ts": None  # Will be filled by caller
        }
        with open(intent_file, 'w', encoding='utf-8') as f:
            json.dump(intent_data, f, indent=2)

        goal_ref = f"bb://{run_id}/embeddings/goal_embed.json"
        intent_ref = f"bb://{run_id}/embeddings/intent_t{turn_id}.json"

    return {
        "user_goal_ref": goal_ref,
        "intent_embed_ref": intent_ref,
        "similarity_s": similarity_s,
        "drift_D": drift_D,
        "embed_model": embed_model
    }


def enrich_turn_with_tdi(
    turn_event: Dict[str, Any],
    goal_text: str,
    bb_root: Path,
    embed_model: str = "text-embedding-004"
) -> Dict[str, Any]:
    """
    Enrich a run.turn.v2 event with computed TDI metrics.

    Args:
        turn_event: run.turn.v2 event dict
        goal_text: User goal text
        bb_root: Blackboard root path
        embed_model: Embedding model name

    Returns:
        dict: Updated turn event with real TDI values
    """
    # Extract intent text (use message as proxy)
    intent_text = turn_event.get("message", "")

    # Compute TDI
    tdi = compute_tdi_for_turn(
        goal_text=goal_text,
        intent_text=intent_text,
        embed_model=embed_model,
        bb_root=bb_root,
        run_id=turn_event.get("run_id"),
        turn_id=turn_event.get("turn_id")
    )

    # Update metrics_trace.tdi
    if "metrics_trace" not in turn_event:
        turn_event["metrics_trace"] = {}

    turn_event["metrics_trace"]["tdi"] = tdi

    return turn_event
