# Plan: PDF → Markdown → Neo4j Knowledge Graph Pipeline

## Context

The MT-phase-2 MAS system currently handles fault knowledge via two mechanisms:
1. `tep_knowledge.py` — local Python dicts (IDV 0-20, sensor mappings), no PDF grounding
2. `me_docs.py` / `DocIndex` — TF-IDF + dense RAG over `TEP_docs/` PDFs

**Problem**: RAG is a black box — when ME cites a chunk, there's no traceable path from claim to source to Neo4j node. `kg_query_fault()` currently returns local dict data only, with no PDF-backed evidence.

**Goal**: Upgrade ME's knowledge layer with a Neo4j KG where:
- Each PDF is parsed into structured `Chunk` nodes (stable, structure-based chunking)
- `Fault`/`Measurement` nodes link to those chunks via `MENTIONED_IN` edges
- `query_fault_with_context()` returns structured data + citation evidence from Neo4j
- ME agent can cite specific chunks: `{claim, evidence_chunk_ids: ["DOWNS_pdf_chunk_0042"]}`

## Critical Correction vs Draft Plan

**The draft's "reusable existing components" table is inaccurate.** None of these exist:
- `tools/pdf_parser.py` — does not exist
- `agents/kg_builder_agent.py` — does not exist
- `tools/neo4j_client.py` — does not exist
- `config/graph_schema.py` — does not exist
- `agents/models.py` — does not exist
- `pipeline/tep_ingestion.py` — does not exist

**All are new files.** Only `tep_knowledge.py` (local ground truth) exists and can seed the Neo4j schema.

**`opendataloader-pdf` does not exist as a PyPI package.** Replace with `pymupdf4llm`, which extends the already-required `pymupdf` to produce LLM-ready markdown with heading/page/bbox metadata (real package, actively maintained).

## Directory Structure (New Files)

```
/home/user/repo/
├── tools/
│   ├── pdf_parser.py        # pymupdf4llm primary, pymupdf fallback
│   └── neo4j_client.py      # MERGE/MATCH helpers + 6 new functions
├── config/
│   ├── tep_schema.py        # port from tep_knowledge.py (TEP domain constants)
│   └── graph_schema.py      # Node labels, relation endpoints, constraint DDL
├── agents/
│   ├── models.py            # ParsedDocument, ExtractionResult, IngestResult
│   └── pdf_parser_agent.py  # Gemini entity extraction (chunk → IDV/XMEAS/XMV)
├── pipeline/
│   └── tep_ingestion.py     # 5-stage ingestion: Parse → Chunk → Extract → Link → Summarize
└── tests/
    ├── test_pdf_parser.py   # unit tests (mock fitz)
    ├── test_neo4j_client.py # unit tests (mock Neo4j driver)
    └── test_tep_ingestion.py# unit tests (mock all I/O)
```

The existing `me_tools.py:kg_query_fault` gets updated last to call Neo4j instead of local dict.

## Data Flow

```
TEP_docs/*.pdf
      │
      ▼
[tools/pdf_parser.py]
  pymupdf4llm → sections list
  {heading, content_md, page, bbox}
  fallback: pymupdf page text, chunked by page
      │
      ▼
[agents/models.py: ParsedDocument]
  file_hash (SHA256[:16]) = doc_id
  sections: list[{heading, content_md, page}]
  parser_used: "pymupdf4llm" | "pymupdf"
      │
      ├──▶ [tools/neo4j_client.py: create_document()]
      │       MERGE (:Document {doc_id})
      │
      ├──▶ [tools/neo4j_client.py: create_chunks()]
      │       validate_chunk() → ≥50 chars, ≤3200 chars
      │       MERGE (:Chunk {chunk_id}) — PART_OF → Document
      │
      ├──▶ [agents/pdf_parser_agent.py: extract_entities()]  ← Gemini API
      │       per-chunk: "which IDV/XMEAS/XMV?"
      │       returns mentions: [{entity_type, entity_name, chunk_id}]
      │
      ├──▶ [tools/neo4j_client.py: link_entities_to_chunks()]
      │       MATCH Fault/Measurement WHERE name=entity_name
      │       CREATE (:Fault)-[:MENTIONED_IN]->(:Chunk)
      │
      └──▶ [tools/neo4j_client.py: update_node_summary_md()]  ← Gemini batch
              collect all MENTIONED_IN chunks per Fault
              generate ~200 token summary_md
              UPDATE Fault.summary_md
```

## Neo4j Schema

**Node labels** (added to `config/graph_schema.py`):
```python
VALID_NODE_LABELS = (
    "Fault", "Measurement", "ManipulatedVar", "ProcessUnit",  # existing TEP
    "Document", "Chunk",                                       # NEW
)
```

**Constraints** (run once on Neo4j startup):
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (n:Document) REQUIRE n.doc_id IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE
CREATE CONSTRAINT IF NOT EXISTS FOR (n:Fault) REQUIRE n.idv_number IS UNIQUE
```

**Document node**:
```python
{doc_id: str, filename: str, title: str, pages: int,
 extracted_at: str, parser: str, authors: str, year: int}
```

**Chunk node**:
```python
{chunk_id: str,        # "{doc_id}_chunk_{index:04d}"
 content_md: str,      # ≤3200 chars of markdown
 heading: str,
 page: int,
 source_doc: str,      # doc_id back-reference
 chunk_index: int,
 keywords: list[str]}  # fast match ["IDV_4", "XMEAS_9"]
```

**Added fields to existing Fault node**:
```python
summary_md: str    # ~200 token cross-doc synthesis
source_doc: str    # primary document doc_id
```

**Relations**:
```cypher
(:Chunk)-[:PART_OF]->(:Document)
(:Fault)-[:MENTIONED_IN]->(:Chunk)
(:Measurement)-[:MENTIONED_IN]->(:Chunk)
(:Document)-[:CITES]->(:Document)       # topology discovery (Pass 3)
(:Chunk)-[:EXTENDS]->(:Chunk)           # topology discovery (Pass 3)
(:Chunk)-[:CONTRADICTS]->(:Chunk)       # topology discovery (Pass 3)
```

## Implementation Steps (in dependency order)

### Step 0: Package Dependencies
File: `requirements.txt`
```
neo4j>=5.0.0          # Neo4j Python driver
pymupdf4llm>=0.0.17   # LLM-ready markdown from PDF (extends pymupdf)
```

### Step 1: `config/tep_schema.py`
Port `tep_knowledge.py` constants (`FAULT_DESCRIPTIONS`, `FAULT_SENSORS`, `PROCESS_UNITS`) as-is. This file serves as ground truth for validating extracted entities.
- No logic changes; just a clean config-layer copy.
- `config/graph_schema.py`: define `VALID_NODE_LABELS`, `RELATION_ENDPOINTS`, `_CONSTRAINTS` list.

### Step 2: `agents/models.py`
```python
@dataclass class ParsedDocument:
    text: str; pages: int; filename: str; file_hash: str
    sections: list[dict]   # [{heading, content_md, page}]
    parser_used: str

@dataclass class ExtractionResult:
    doc_id: str; entities: list[dict]; mentions: list[dict]
    metadata: dict; sections: list[dict]

@dataclass class IngestResult:
    doc_id: str; chunks_created: int; entities_found: int
    relations_created: int; warnings: list[str]; status: str
```

### Step 3: `tools/pdf_parser.py`
```python
def parse_pdf(pdf_path: str) -> ParsedDocument:
    """pymupdf4llm → pymupdf fallback; always returns ParsedDocument with sections."""
```

**pymupdf4llm path**: calls `pymupdf4llm.to_markdown(pdf_path, page_chunks=True)` → returns list of page dicts with `text`, `metadata.heading` → assemble sections.

**pymupdf fallback**: open with fitz, extract text per page, treat each page as a section with heading = "Page N".

**Section→chunk logic** (Python only, no LLM):
```python
def _split_into_chunks(sections: list[dict]) -> list[dict]:
    # If section.content_md > 3200 chars: split on blank lines (paragraph boundaries)
    # If section.content_md < 50 chars: discard (orphan heading)
    # Tables: header row pinned to same chunk as first data rows
    # chunk_id = f"{doc_id}_chunk_{index:04d}"
```

### Step 4: `tools/neo4j_client.py`
**Constructor**: reads `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` from env. Runs `_ensure_constraints()` on connect.

**6 new functions** (all idempotent via MERGE):
```python
def create_document(doc_id, filename, pages, parser_used, ...) -> str
def create_chunks(doc_id, sections) -> dict  # {"chunks_created": N, "warnings": []}
def link_entities_to_chunks(mentions: list[dict]) -> int
def update_node_summary_md(name, label, summary_md, source_doc) -> None
def query_with_context(label, name_prop, value) -> dict
def query_fault_with_context(fault_id: int) -> dict  # primary query for ME agent
```

`query_fault_with_context` Cypher:
```cypher
MATCH (f:Fault {idv_number: $fault_id})
OPTIONAL MATCH (f)-[:MENTIONED_IN]->(c:Chunk)
OPTIONAL MATCH (c)-[:PART_OF]->(d:Document)
RETURN f, collect({chunk_id:c.chunk_id, content_md:c.content_md,
                   heading:c.heading, page:c.page,
                   source_doc:d.filename})[..3] AS evidence
```

Returns:
```json
{"fault_id": 4, "description": "...", "diagnostic_sensors": [...],
 "summary_md": "...", "context_chunks": ["# Section...", ...],
 "evidence": [{"chunk_id":"...", "page":12, "source_doc":"DOWNS.pdf", ...}]}
```

### Step 5: `agents/pdf_parser_agent.py`
**System prompt** (TEP-mode, ≤200 tokens):
> "Identify TEP entities in this text. Output JSON array only:
> [{entity_type: Fault|Measurement|ManipulatedVar, entity_name: IDV_N|XMEAS_N|XMV_N}]
> Use IDV_N for fault mentions ('cooling water' = IDV_4, IDV_11, IDV_14)."

**Function**:
```python
def extract_entities_from_chunk(chunk_text: str, chunk_id: str) -> list[dict]:
    """Returns [{entity_type, entity_name, chunk_id, sentence}]"""
```

Calls Gemini once per chunk. Falls back to regex (IDV_\d+, XMEAS_\d+, XMV_\d+) if LLM returns invalid JSON.

### Step 6: `pipeline/tep_ingestion.py`
5-stage pipeline with try/except at each stage:
```python
def ingest_pdf(pdf_path: str) -> IngestResult:
    # Stage 1: Parse
    parsed = parse_pdf(pdf_path)
    # Stage 2: Chunk → Neo4j
    doc_id = create_document(parsed.file_hash, ...)
    chunk_result = create_chunks(doc_id, parsed.sections)
    # Stage 3: Entity extraction (per chunk, sequential to manage API rate)
    mentions = []
    for chunk in parsed.sections:
        mentions += extract_entities_from_chunk(chunk["content_md"], chunk["chunk_id"])
    # Stage 4: Link entities → chunks
    n_rels = link_entities_to_chunks(mentions)
    # Stage 5: summary_md (batch, non-blocking)
    _generate_summaries_async(doc_id)
    return IngestResult(...)

def ingest_tep_docs(pdf_dir: str) -> dict:
    for pdf_path in sorted(glob(f"{pdf_dir}/*.pdf")):
        ingest_pdf(pdf_path)
```

### Step 7: Update `me_tools.py:kg_query_fault`
Change from local lookup to Neo4j call:
```python
@tool("kg_query_fault")
def kg_query_fault(fault_id: int) -> str:
    """Query TEP fault knowledge + PDF evidence from Neo4j."""
    try:
        from tools.neo4j_client import Neo4jClient
        client = Neo4jClient()
        result = client.query_fault_with_context(fault_id)
        return json.dumps(result, ensure_ascii=False)
    except Exception:
        # Fallback to local dict if Neo4j unavailable
        from tep_knowledge import lookup_fault
        return json.dumps(lookup_fault(fault_id), ensure_ascii=False)
```

The fallback ensures the MAS system keeps working without Neo4j.

## TDD Plan (CLAUDE.md rule: tests first)

| Test file | Tests | What it covers |
|-----------|-------|---------------|
| `tests/test_pdf_parser.py` | 8 | section extraction, chunk splitting, ≤3200 cap, orphan discard |
| `tests/test_neo4j_client.py` | 10 | mock driver: create_document, create_chunks, link_entities, query_fault_with_context return shape |
| `tests/test_tep_ingestion.py` | 6 | full pipeline with mocked parser + neo4j + LLM |

All tests use mocks (no real Neo4j, no real Gemini API call). Regression: existing 63 tests stay green.

## Dependencies Between Steps

```
Step 0 (requirements)
  └─▶ Step 1 (config/)
        └─▶ Step 2 (models.py)
              ├─▶ Step 3 (pdf_parser.py)
              └─▶ Step 4 (neo4j_client.py)
                    ├─▶ Step 5 (pdf_parser_agent.py)
                    └─▶ Step 6 (tep_ingestion.py)
                          └─▶ Step 7 (me_tools.py update)
```

## Verification

```bash
# 1. Regression — existing tests still green
pytest tests/ -q  # expect 63 passed

# 2. New unit tests
pytest tests/test_pdf_parser.py tests/test_neo4j_client.py tests/test_tep_ingestion.py -v

# 3. Integration (requires NEO4J_URI + GOOGLE_API_KEY env vars)
python pipeline/tep_ingestion.py --pdf-dir TEP_docs/ --dry-run  # parse only, no Neo4j write
NEO4J_URI=bolt://localhost:7687 python pipeline/tep_ingestion.py --pdf-dir TEP_docs/

# 4. Spot check query
python -c "
from tools.neo4j_client import Neo4jClient
r = Neo4jClient().query_fault_with_context(4)
assert r['fault_id'] == 4
assert len(r['diagnostic_sensors']) >= 1
assert len(r['evidence']) >= 1  # ≥1 chunk returned
assert r['evidence'][0]['content_md'].startswith('#') or len(r['evidence'][0]['content_md']) > 10
print('PASS:', r['description'])
"

# 5. me_tools fallback works without Neo4j
python -c "
import os; os.environ.pop('NEO4J_URI', None)
from me_tools import kg_query_fault
r = kg_query_fault.invoke({'fault_id': 4})
import json; d = json.loads(r)
assert d['fault_id'] == 4
print('fallback PASS')
"
```

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `pymupdf4llm` not yet installed | Add to requirements.txt; `pip install pymupdf4llm` before tests |
| Neo4j not running (dev env) | `kg_query_fault` fallback to `tep_knowledge.lookup_fault()` |
| Gemini entity extraction misses IDV mentions | Regex fallback (`IDV_\d+`, `XMEAS_\d+`) |
| Chunk > 64KB Neo4j property limit | Hard cap at 3200 chars in `create_chunks()` |
| Section < 50 chars (orphan heading) | Discard in `validate_chunk()`; log warning |