"""TEP fault diagnosis lookup tables.

Lightweight local copy of TEP domain knowledge — no Neo4j dependency.
Mirrors the constants in manufacturing-kg-agent/config/tep_schema.py.
"""
from __future__ import annotations
from typing import Final

FAULT_DESCRIPTIONS: Final[dict[int, str]] = {
    0:  "Normal operation (no fault)",
    1:  "A/C feed ratio step change — B composition constant",
    2:  "B composition step change — A/C ratio constant",
    3:  "D feed temperature step change",
    4:  "Reactor cooling water inlet temperature step change",
    5:  "Condenser cooling water inlet temperature step change",
    6:  "A feed loss (stream 1 valve stuck)",
    7:  "C header pressure loss (stream 4 reduced)",
    8:  "A, B, C feed composition random variation",
    9:  "D feed temperature random variation",
    10: "C feed temperature random variation",
    11: "Reactor cooling water inlet temperature random variation",
    12: "Condenser cooling water inlet temperature random variation",
    13: "Reaction kinetics slow drift",
    14: "Reactor cooling water valve sticking",
    15: "Condenser cooling water valve sticking",
    16: "Unknown fault 16",
    17: "Unknown fault 17",
    18: "Unknown fault 18",
    19: "Unknown fault 19",
    20: "Unknown fault 20",
}

# fault_id -> diagnostic sensor columns in tep_combined.db
FAULT_SENSORS: Final[dict[int, list[str]]] = {
    4:  ["xmeas_9", "xmeas_7", "xmv_6"],
    11: ["xmeas_9", "xmeas_7", "xmv_6"],
    14: ["xmeas_9", "xmeas_7", "xmv_6"],
    1:  ["xmeas_1", "xmeas_2", "xmeas_3", "xmeas_4", "xmeas_6"],
    2:  ["xmeas_1", "xmeas_2", "xmeas_3", "xmeas_4", "xmeas_6"],
    3:  ["xmeas_1", "xmeas_2", "xmeas_3", "xmeas_4", "xmeas_6"],
    6:  ["xmeas_1", "xmeas_2", "xmeas_3", "xmeas_4", "xmeas_6"],
    7:  ["xmeas_1", "xmeas_2", "xmeas_3", "xmeas_4", "xmeas_6"],
    5:  ["xmeas_11", "xmeas_12", "xmeas_13", "xmeas_14", "xmeas_22", "xmv_7"],
    12: ["xmeas_11", "xmeas_12", "xmeas_13", "xmeas_14", "xmeas_22", "xmv_7"],
    15: ["xmeas_11", "xmeas_12", "xmeas_13", "xmeas_14", "xmeas_22", "xmv_7"],
    8:  ["xmeas_23", "xmeas_24", "xmeas_25", "xmeas_26", "xmeas_27", "xmeas_28"],
    9:  ["xmeas_23", "xmeas_24", "xmeas_25", "xmeas_26", "xmeas_27", "xmeas_28"],
    10: ["xmeas_23", "xmeas_24", "xmeas_25", "xmeas_26", "xmeas_27", "xmeas_28"],
    13: ["xmeas_9", "xmeas_7"],
}

# unit_name -> {measurements, manipulated, description}
PROCESS_UNITS: Final[dict[str, dict]] = {
    "Reactor": {
        "description": "Main reaction vessel where A+C+D+E -> G+H",
        "measurements": ["xmeas_7", "xmeas_8", "xmeas_9", "xmeas_10", "xmeas_11"],
        "manipulated": ["xmv_3", "xmv_4", "xmv_6"],
    },
    "Separator": {
        "description": "Vapor-liquid separator downstream of reactor",
        "measurements": ["xmeas_12", "xmeas_13", "xmeas_14", "xmeas_15"],
        "manipulated": ["xmv_7"],
    },
    "Condenser": {
        "description": "Overhead condenser on separator",
        "measurements": ["xmeas_21", "xmeas_22"],
        "manipulated": ["xmv_11"],
    },
    "StripperColumn": {
        "description": "Stripper column for product purification",
        "measurements": ["xmeas_16", "xmeas_17", "xmeas_18", "xmeas_19", "xmeas_20"],
        "manipulated": ["xmv_8", "xmv_9"],
    },
    "FeedSystem": {
        "description": "Feed streams 1-4 (A, D, E, C+air)",
        "measurements": ["xmeas_1", "xmeas_2", "xmeas_3", "xmeas_4"],
        "manipulated": ["xmv_1", "xmv_2", "xmv_3", "xmv_4"],
    },
}


def lookup_fault(fault_id: int) -> dict:
    """Return structured fault knowledge for a given IDV fault ID."""
    if fault_id not in FAULT_DESCRIPTIONS:
        return {"error": f"Unknown fault_id={fault_id}. Valid range: 0-20."}

    sensor_cols = FAULT_SENSORS.get(fault_id, [])
    sensor_details = []
    for col in sensor_cols:
        unit = next(
            (u for u, info in PROCESS_UNITS.items()
             if col in info.get("measurements", []) + info.get("manipulated", [])),
            "Unknown",
        )
        sensor_details.append({"column": col, "process_unit": unit})

    return {
        "fault_id": fault_id,
        "fault_name": f"IDV_{fault_id}",
        "description": FAULT_DESCRIPTIONS[fault_id],
        "diagnostic_sensors": sensor_details,
        "source": "TEP knowledge base (Downs & Vogel 1993)",
    }


def match_fault_by_sensors_local(sensors: list[str], top_k: int = 3) -> list[dict]:
    """Reverse-lookup candidate faults from a list of deviant sensor names.

    Scores each fault by Jaccard overlap between the input sensors and the fault's
    known diagnostic sensors. Returns top_k candidates sorted by score (descending),
    breaking ties on smaller fault_id.

    Args:
        sensors: Sensor column names (e.g. ["xmeas_9", "xmv_6"]).
        top_k: Maximum number of candidates to return.

    Returns:
        List of {"fault_id", "fault_name", "description", "score", "matched"} dicts.
        Empty list if input is empty.
    """
    if not sensors:
        return []

    query = set(sensors)
    scored: list[dict] = []
    for fid, fsensors in FAULT_SENSORS.items():
        ref = set(fsensors)
        union = query | ref
        if not union:
            continue
        matched = sorted(query & ref)
        if not matched:
            continue
        score = len(matched) / len(union)
        scored.append({
            "fault_id": fid,
            "fault_name": f"IDV_{fid}",
            "description": FAULT_DESCRIPTIONS.get(fid, ""),
            "score": round(score, 4),
            "matched": matched,
        })

    scored.sort(key=lambda r: (-r["score"], r["fault_id"]))
    return scored[:top_k]
