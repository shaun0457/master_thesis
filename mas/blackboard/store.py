# mas/blackboard/store.py
"""
Blackboard Store: Run-isolated, Schema-validated Storage for O-MAS Experiments.

This module implements the core storage backend for the blackboard communication
pattern used in multi-agent collaboration. Each experimental run operates in
complete isolation with its own namespace, ensuring reproducibility and
preventing cross-contamination between runs.

Design Principles:
    1. Run Isolation: All artifacts are stored under <root>/<run_id>/
    2. Schema Validation: Optional JSON Schema validation on write
    3. Atomic Writes: Temp file + rename prevents partial writes
    4. Content Hashing: SHA-256 enables integrity verification

Storage Layout:
    data/blackboard/
    └── <run_id>/
        ├── context/
        │   └── task.json           # Task description
        ├── data/
        │   └── xmeas_v1.csv        # Input datasets
        ├── analysis/
        │   └── correlation.json    # Analysis artifacts
        ├── diagnostics/
        │   └── fault_tree.json     # Diagnostic results
        ├── plans/
        │   └── action_plan.json    # Execution plans
        └── reports/
            └── final.md            # Final reports

Event Logging (separate from blackboard):
    data/runs/<run_id>/
    ├── turn_log.jsonl              # All turn events
    ├── bb_writes.jsonl             # Blackboard write events
    ├── bb_reads.jsonl              # Blackboard read events
    ├── stdout.txt                  # Complete execution log
    └── final_output.txt            # Extracted final report

Author: Cheng-Ting Chen
Thesis: Observable Multi-Agent Systems (O-MAS)
"""

import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
import jsonschema
import tempfile
import shutil
import pandas as pd


class BlackboardStore:
    """
    Run-isolated blackboard storage with schema validation.

    This class provides the interface for agents to read and write artifacts
    to a shared blackboard. Each run operates in its own namespace to ensure
    complete isolation between experiments.

    The blackboard supports multiple data formats:
        - JSON: Structured data (configs, analysis results, plans)
        - JSONL: Append-only logs (turn events, metrics)
        - Parquet: Tabular data (datasets, time series)

    All writes are atomic (temp file + rename) to prevent corruption from
    crashes or concurrent access.

    Attributes:
        root (Path): Root directory for all blackboard data
        run_id (str): Unique identifier for this run
        run_root (Path): This run's namespace directory

    Example:
        >>> store = BlackboardStore(Path("data/blackboard"), "debate-s42-20241115")
        >>> store.write_json("bb://context/task.json", {"query": "Diagnose fault"})
        >>> task = store.read_json("bb://context/task.json")
    """

    def __init__(self, root: Path, run_id: str) -> None:
        """
        Initialize a BlackboardStore for a specific experimental run.

        Creates the run namespace directory if it doesn't exist.

        Args:
            root: Root directory for all blackboard data.
                  Typically: ./data/blackboard
            run_id: Unique run identifier that enforces isolation.
                    Format: <protocol>-s<seed>-<timestamp>
                    Example: debate-s42-20241115-143022

        Example:
            >>> store = BlackboardStore(
            ...     root=Path("data/blackboard"),
            ...     run_id="debate-s42-20241115-143022"
            ... )
            >>> print(store.run_root)
            data/blackboard/debate-s42-20241115-143022
        """
        self.root = Path(root)
        self.run_id = run_id
        self.run_root = self.root / run_id

        # Schema cache to avoid repeated disk reads
        self._schema_cache: Dict[str, Dict[str, Any]] = {}

    def resolve(self, uri: str) -> Path:
        """
        Map a bb:// URI to a local filesystem path.

        This method translates blackboard URIs into absolute local paths
        within this run's isolated namespace.

        URI Format:
            bb://<namespace>/<artifact>
            The namespace is a logical grouping (context, data, analysis, etc.)

        Args:
            uri: Blackboard URI string.
                 Must start with "bb://"
                 Examples:
                     - "bb://context/task.json"
                     - "bb://data/xmeas_v1.csv"
                     - "bb://analysis/correlation.json"

        Returns:
            Path: Absolute local path to the artifact.
                  Example: data/blackboard/run-123/context/task.json

        Raises:
            ValueError: If URI doesn't start with "bb://"

        Example:
            >>> store = BlackboardStore(Path("data/bb"), "run-123")
            >>> path = store.resolve("bb://context/task.json")
            >>> print(path)
            data/bb/run-123/context/task.json
        """
        if not uri.startswith("bb://"):
            raise ValueError(f"Invalid blackboard URI: {uri} (must start with 'bb://')")

        # Strip "bb://" prefix and resolve relative to run root
        rel_path = uri[5:]  # Remove "bb://"
        return self.run_root / rel_path

    def write_json(self, uri: str, obj: dict, schema_id: Optional[str] = None) -> dict:
        """
        Write a JSON object to the blackboard atomically.

        This method provides crash-safe writes by:
        1. Writing to a temporary file in the same directory
        2. Atomically renaming the temp file to the target path

        This ensures that readers never see partial/corrupted data.

        Args:
            uri: Blackboard URI for the target location.
                 Example: "bb://analysis/correlation.json"
            obj: Dictionary to serialize as JSON.
                 Must be JSON-serializable (no custom objects).
            schema_id: Optional JSON Schema ID for validation.
                       If provided, the object is validated before writing.
                       Example: "run.turn.v2"

        Returns:
            dict: Write metadata containing:
                - uri (str): Echo of input URI
                - hash (str): SHA-256 hash of content (64 hex chars)
                - path (str): Absolute path where file was written

        Raises:
            jsonschema.ValidationError: If schema validation fails
            FileNotFoundError: If schema_id specified but schema file not found

        Example:
            >>> result = store.write_json(
            ...     "bb://analysis/stats.json",
            ...     {"mean": 42.5, "std": 3.2}
            ... )
            >>> print(result["hash"][:16])  # First 16 chars of hash
            "a1b2c3d4e5f67890"
        """
        # Validate against schema if requested
        if schema_id is not None:
            self._validate_schema(obj, schema_id)

        path = self.resolve(uri)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file in same directory, then rename
        # This ensures readers never see partial writes
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            delete=False,
            suffix='.tmp'
        ) as tmp:
            json.dump(obj, tmp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp_path = Path(tmp.name)

        # Atomic rename (POSIX guarantees atomicity for same-filesystem rename)
        shutil.move(str(tmp_path), str(path))

        return {
            "uri": uri,
            "hash": self.hash_content(obj),
            "path": str(path)
        }

    def append_jsonl(self, uri: str, obj: dict, schema_id: Optional[str] = None) -> dict:
        """
        Append a JSON object as a line to a JSONL (JSON Lines) file.

        JSONL format stores one JSON object per line, enabling:
        - Efficient append operations (no need to rewrite entire file)
        - Streaming reads (process line-by-line without loading all)
        - Easy concatenation of log files

        Used for event logs: turn_log.jsonl, bb_writes.jsonl, bb_reads.jsonl

        Args:
            uri: Blackboard URI for the JSONL file.
                 Example: "bb://logs/turn_log.jsonl"
            obj: Dictionary to serialize as a single JSON line.
            schema_id: Optional JSON Schema ID for validation.

        Returns:
            dict: Write metadata (same structure as write_json)

        Raises:
            jsonschema.ValidationError: If schema validation fails

        Example:
            >>> store.append_jsonl(
            ...     "bb://logs/events.jsonl",
            ...     {"event": "turn_start", "turn": 5, "agent": "supervisor"}
            ... )
        """
        # Validate against schema if requested
        if schema_id is not None:
            self._validate_schema(obj, schema_id)

        path = self.resolve(uri)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Append mode - file is created if doesn't exist
        with open(path, 'a', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, sort_keys=True)
            f.write('\n')  # Newline delimiter

        return {
            "uri": uri,
            "hash": self.hash_content(obj),
            "path": str(path)
        }

    def read_json(self, uri: str) -> dict:
        """
        Read a JSON object from the blackboard.

        Args:
            uri: Blackboard URI to read.
                 Example: "bb://context/task.json"

        Returns:
            dict: Parsed JSON content as a dictionary.

        Raises:
            FileNotFoundError: If the artifact doesn't exist.
            json.JSONDecodeError: If file contains invalid JSON.

        Example:
            >>> task = store.read_json("bb://context/task.json")
            >>> print(task["query"])
            "Diagnose the fault in reactor system"
        """
        path = self.resolve(uri)
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def read_parquet(self, uri: str) -> dict:
        """
        Read a Parquet file from the blackboard.

        Parquet is a columnar storage format efficient for tabular data.
        Used for datasets like sensor readings, time series, etc.

        Args:
            uri: Blackboard URI to read.
                 Example: "bb://data/xmeas_v1.parquet"

        Returns:
            dict: Dictionary containing:
                - data (list): List of row dictionaries (records format)
                - columns (list): Column names

        Raises:
            FileNotFoundError: If the file doesn't exist.

        Example:
            >>> result = store.read_parquet("bb://data/sensors.parquet")
            >>> print(result["columns"])
            ["timestamp", "temperature", "pressure"]
            >>> print(len(result["data"]))  # Number of rows
            1000
        """
        path = self.resolve(uri)
        df = pd.read_parquet(str(path), engine='pyarrow')

        # Convert to dict in records format for JSON compatibility
        return {
            "data": df.to_dict(orient='records'),
            "columns": df.columns.tolist()
        }

    def exists(self, uri: str) -> bool:
        """
        Check if a blackboard artifact exists.

        Args:
            uri: Blackboard URI to check.

        Returns:
            bool: True if the artifact exists on disk.

        Example:
            >>> if store.exists("bb://analysis/results.json"):
            ...     results = store.read_json("bb://analysis/results.json")
        """
        return self.resolve(uri).exists()

    def hash_content(self, obj: dict) -> str:
        """
        Compute SHA-256 hash of a dictionary.

        Uses canonical JSON serialization (sorted keys, no whitespace)
        to ensure consistent hashes regardless of dict ordering.

        The hash enables:
        - Integrity verification (detect tampering/corruption)
        - Deduplication (identify identical artifacts)
        - Change detection (compare versions)

        Args:
            obj: Dictionary to hash.

        Returns:
            str: Lowercase hexadecimal SHA-256 digest (64 characters).

        Example:
            >>> hash1 = store.hash_content({"a": 1, "b": 2})
            >>> hash2 = store.hash_content({"b": 2, "a": 1})  # Same content
            >>> assert hash1 == hash2  # Order doesn't matter
        """
        # Canonical serialization: sorted keys, minimal whitespace, ASCII
        canonical_json = json.dumps(
            obj,
            ensure_ascii=True,
            sort_keys=True,
            separators=(',', ':')
        )
        return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

    def _validate_schema(self, obj: dict, schema_id: str) -> None:
        """
        Validate an object against a JSON Schema.

        Schemas are loaded from the /schema directory and cached for reuse.
        Validation ensures data integrity and catches structural errors early.

        Args:
            obj: Dictionary to validate.
            schema_id: Schema identifier matching filename (without .json).
                       Example: "run.turn.v2" loads schema/run.turn.v2.json

        Raises:
            jsonschema.ValidationError: If validation fails.
                Contains detailed error message with path to invalid field.
            FileNotFoundError: If schema file not found.

        Example:
            >>> store._validate_schema(
            ...     {"turn_index": 5, "role": "supervisor"},
            ...     "run.turn.v2"
            ... )  # Raises ValidationError if missing required fields
        """
        # Load and cache schema
        if schema_id not in self._schema_cache:
            schema_path = Path(__file__).parents[2] / "schema" / f"{schema_id}.json"
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema not found: {schema_path}")

            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)

            self._schema_cache[schema_id] = schema

        # Validate against cached schema
        jsonschema.validate(instance=obj, schema=self._schema_cache[schema_id])
