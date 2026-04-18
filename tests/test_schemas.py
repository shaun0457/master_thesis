# tests/test_schemas.py
"""Tests for JSON Schema files in schema/."""

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_DIR = Path(__file__).parents[1] / "schema"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# run.turn.v2
# ---------------------------------------------------------------------------

def _valid_turn(**overrides) -> dict:
    base = {
        "schema":     "run.turn.v2",
        "run_id":     "test-run-001",
        "turn_index": 0,
        "role":       "supervisor",
        "message":    "Hello team",
        "intent":     "delegate",
        "action":     {"target": "de"},
        "ts":         "2024-11-15T14:30:22Z",
    }
    base.update(overrides)
    return base


class TestRunTurnV2:
    schema = load_schema("run.turn.v2")

    def test_valid_turn_passes(self):
        jsonschema.validate(_valid_turn(), self.schema)

    def test_extra_fields_allowed(self):
        jsonschema.validate(_valid_turn(extra_field="ok"), self.schema)

    @pytest.mark.parametrize("missing", [
        "schema", "run_id", "turn_index", "role", "message", "intent", "action", "ts"
    ])
    def test_missing_required_field_fails(self, missing):
        ev = _valid_turn()
        del ev[missing]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ev, self.schema)

    def test_turn_index_must_be_integer(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_valid_turn(turn_index="zero"), self.schema)

    def test_action_must_be_object(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_valid_turn(action="bad"), self.schema)


# ---------------------------------------------------------------------------
# router.event.v2
# ---------------------------------------------------------------------------

def _valid_router(**overrides) -> dict:
    base = {
        "schema":     "router.event.v2",
        "run_id":     "test-run-001",
        "turn_index": 1,
        "sender":     "de",
        "status":     "ok",
        "violations": [],
        "next_owner": "supervisor",
        "ts":         "2024-11-15T14:30:22Z",
    }
    base.update(overrides)
    return base


class TestRouterEventV2:
    schema = load_schema("router.event.v2")

    def test_valid_router_event_passes(self):
        jsonschema.validate(_valid_router(), self.schema)

    def test_violations_must_be_array(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_valid_router(violations="none"), self.schema)

    @pytest.mark.parametrize("missing", [
        "schema", "run_id", "turn_index", "sender", "status", "violations", "next_owner", "ts"
    ])
    def test_missing_required_field_fails(self, missing):
        ev = _valid_router()
        del ev[missing]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ev, self.schema)


# ---------------------------------------------------------------------------
# bb.write.v1
# ---------------------------------------------------------------------------

def _valid_write(**overrides) -> dict:
    base = {
        "schema":        "bb.write.v1",
        "run_id":        "test-run-001",
        "write_id":      "write-de-t3",
        "turn_index":    3,
        "writer_role":   "de",
        "topic_id":      "analysis",
        "artifact":      "bb://analysis/result.json",
        "artifact_kind": "json",
        "ts":            "2024-11-15T14:30:22Z",
    }
    base.update(overrides)
    return base


class TestBbWriteV1:
    schema = load_schema("bb.write.v1")

    def test_valid_write_event_passes(self):
        jsonschema.validate(_valid_write(), self.schema)

    @pytest.mark.parametrize("missing", [
        "schema", "run_id", "write_id", "turn_index", "writer_role",
        "topic_id", "artifact", "artifact_kind", "ts",
    ])
    def test_missing_required_field_fails(self, missing):
        ev = _valid_write()
        del ev[missing]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ev, self.schema)


# ---------------------------------------------------------------------------
# run.read.v1
# ---------------------------------------------------------------------------

def _valid_read(**overrides) -> dict:
    base = {
        "schema":        "run.read.v1",
        "run_id":        "test-run-001",
        "read_id":       "read-ds-t4",
        "turn_index":    4,
        "reader_role":   "ds",
        "artifact":      "bb://analysis/result.json",
        "artifact_kind": "json",
        "write_ref":     {"event_id": "write-de-t3", "turn_index": 3, "writer_role": "de"},
        "ts":            "2024-11-15T14:30:22Z",
    }
    base.update(overrides)
    return base


class TestRunReadV1:
    schema = load_schema("run.read.v1")

    def test_valid_read_event_passes(self):
        jsonschema.validate(_valid_read(), self.schema)

    def test_write_ref_must_be_object(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_valid_read(write_ref="bad"), self.schema)

    @pytest.mark.parametrize("missing", [
        "schema", "run_id", "read_id", "turn_index", "reader_role",
        "artifact", "artifact_kind", "write_ref", "ts",
    ])
    def test_missing_required_field_fails(self, missing):
        ev = _valid_read()
        del ev[missing]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ev, self.schema)
