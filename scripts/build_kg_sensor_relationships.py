"""Enrich Neo4j KG with Sensor nodes and (Fault)-[:HAS_SENSOR]->(Sensor) edges.

Source: tep_knowledge.FAULT_SENSORS maps fault_id → diagnostic sensor names.
Cypher is idempotent (MERGE on both nodes and relationships).

Required env vars:
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

Usage:
    python scripts/build_kg_sensor_relationships.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

# add parent to path so we can import tep_knowledge
_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(_HERE)
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from knowledge.tep_knowledge import FAULT_SENSORS  # noqa: E402

UPSERT_SENSOR = """
MERGE (s:Sensor {name: $name})
ON CREATE SET s.created_at = timestamp()
RETURN s.name AS name
"""

LINK_FAULT_SENSOR = """
MATCH (f:Fault {idv_number: $fault_id})
MERGE (s:Sensor {name: $sensor})
MERGE (f)-[r:HAS_SENSOR]->(s)
ON CREATE SET r.created_at = timestamp(), r.weight = $weight
RETURN f.idv_number AS fault_id, s.name AS sensor
"""


def _summarise() -> list[tuple[int, list[str]]]:
    return sorted(FAULT_SENSORS.items())


def run(dry_run: bool = False) -> int:
    pairs = _summarise()
    total = sum(len(sensors) for _, sensors in pairs)

    if dry_run:
        print("[dry-run] would write to Neo4j:")
        for fid, sensors in pairs:
            print(f"  Fault {fid}: {sensors}")
        print(f"[dry-run] total relationships: {total}")
        return total

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not uri:
        raise EnvironmentError("NEO4J_URI not set — cannot connect")

    from neo4j import GraphDatabase

    written = 0
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            sensors_seen: set[str] = set()
            for fid, sensors in pairs:
                for sensor in sensors:
                    if sensor not in sensors_seen:
                        session.run(UPSERT_SENSOR, name=sensor)
                        sensors_seen.add(sensor)
                    session.run(
                        LINK_FAULT_SENSOR,
                        fault_id=fid,
                        sensor=sensor,
                        weight=1.0,
                    )
                    written += 1
            print(f"[ok] upserted {len(sensors_seen)} sensor nodes, "
                  f"{written} HAS_SENSOR relationships across {len(pairs)} faults")
    finally:
        driver.close()
    return written


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = p.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
