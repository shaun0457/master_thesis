"""Neo4j KG query wrapper for ME agent — KG-5.

Provides query_fault_kg() which:
  1. Queries Neo4j AuraDB for Fault node + MENTIONED_IN evidence chunks
  2. Falls back to local tep_knowledge.lookup_fault() on any failure

Reads NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD from environment.
If any env var is missing, silently returns local fallback (no crash).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_kg_driver = None


def _get_kg_driver():
    """Lazy singleton neo4j driver. Raises if env vars missing or driver unavailable."""
    global _kg_driver
    if _kg_driver is not None:
        return _kg_driver

    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER", "")
    password = os.environ.get("NEO4J_PASSWORD", "")

    if not uri:
        raise EnvironmentError("NEO4J_URI not set — Neo4j KG unavailable")

    from neo4j import GraphDatabase
    _kg_driver = GraphDatabase.driver(uri, auth=(user, password))
    return _kg_driver


def close_kg_driver() -> None:
    global _kg_driver
    if _kg_driver is not None:
        _kg_driver.close()
        _kg_driver = None


_FAULT_QUERY = (
    "MATCH (f:Fault {idv_number: $fid}) "
    "OPTIONAL MATCH (f)-[:MENTIONED_IN]->(c:Chunk) "
    "OPTIONAL MATCH (c)-[:PART_OF]->(d:Document) "
    "RETURN f.description AS desc, f.summary_md AS summary_md, "
    "collect({"
    "  chunk_id: c.chunk_id, content_md: c.content_md, "
    "  heading: c.heading, page: c.page, "
    "  source_doc: d.filename, section_type: c.section_type"
    "})[..3] AS evidence"
)


def query_fault_kg(fault_id: int) -> dict[str, Any]:
    """Query TEP fault knowledge from Neo4j KG with local fallback.

    Args:
        fault_id: IDV fault number (0-20).

    Returns:
        Dict with fault_id, fault_name, description, diagnostic_sensors,
        summary_md, evidence, context_chunks, source.
        Falls back to tep_knowledge on any Neo4j failure.
    """
    from tep_knowledge import lookup_fault

    # Local baseline is always computed (authoritative for diagnostic_sensors)
    local = lookup_fault(fault_id)
    if "error" in local:
        return local

    # Attempt Neo4j enrichment
    try:
        driver = _get_kg_driver()
        with driver.session() as session:
            rec = session.run(_FAULT_QUERY, fid=fault_id).single()

        if rec is None:
            logger.debug("Neo4j: no Fault node for IDV_%d, using local fallback", fault_id)
            return {**local, "source": "tep_knowledge (local fallback)",
                    "evidence": [], "context_chunks": [], "summary_md": ""}

        evidence = [e for e in (rec["evidence"] or []) if e.get("chunk_id")]
        return {
            **local,
            "description": rec["desc"] or local["description"],
            "summary_md": rec["summary_md"] or "",
            "evidence": evidence,
            "context_chunks": [e["content_md"] for e in evidence if e.get("content_md")],
            "source": "Neo4j KG + PDF evidence",
        }

    except Exception as exc:
        logger.warning("Neo4j query failed for IDV_%d (%s), using local fallback", fault_id, exc)
        return {**local, "source": "tep_knowledge (local fallback)",
                "evidence": [], "context_chunks": [], "summary_md": ""}


_MATCH_FAULT_BY_SENSORS_QUERY = (
    "MATCH (s:Sensor) WHERE s.name IN $sensors "
    "MATCH (f:Fault)-[:HAS_SENSOR]->(s) "
    "WITH f, count(s) AS hits, collect(s.name) AS matched "
    "RETURN f.idv_number AS fault_id, f.description AS description, "
    "       hits, matched "
    "ORDER BY hits DESC LIMIT $top_k"
)


def match_fault_by_sensors(sensors: list[str], top_k: int = 3) -> list[dict]:
    """Reverse-lookup candidate faults from observed deviant sensors.

    Neo4j-primary with local fallback. Mirrors the pattern of query_fault_kg.

    Args:
        sensors: Sensor column names (e.g. ["xmeas_9", "xmv_6"]).
        top_k: Maximum number of candidates.

    Returns:
        List of {"fault_id", "fault_name", "description", "score", "matched", "source"}
        sorted by score descending. Empty list on empty input.
    """
    from tep_knowledge import match_fault_by_sensors_local

    if not sensors:
        return []

    # Local Jaccard is always computed (used for score even when Neo4j wins)
    local = match_fault_by_sensors_local(sensors, top_k=top_k)

    try:
        driver = _get_kg_driver()
        with driver.session() as session:
            records = list(session.run(
                _MATCH_FAULT_BY_SENSORS_QUERY,
                sensors=list(sensors),
                top_k=int(top_k),
            ))
        if not records:
            logger.debug("Neo4j: no HAS_SENSOR matches for %s, using local fallback", sensors)
            return [{**r, "source": "tep_knowledge (local fallback)"} for r in local]

        query_set = set(sensors)
        out: list[dict] = []
        for rec in records:
            matched = list(rec["matched"] or [])
            # score: jaccard between input sensors and matched
            union_size = len(query_set | set(matched))
            score = round(len(matched) / union_size, 4) if union_size else 0.0
            fid = int(rec["fault_id"]) if rec["fault_id"] is not None else -1
            out.append({
                "fault_id": fid,
                "fault_name": f"IDV_{fid}",
                "description": rec["description"] or "",
                "score": score,
                "matched": sorted(matched),
                "source": "Neo4j KG",
            })
        return out

    except Exception as exc:
        logger.warning("Neo4j match_fault_by_sensors failed (%s), using local fallback", exc)
        return [{**r, "source": "tep_knowledge (local fallback)"} for r in local]
