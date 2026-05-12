"""Build tep_combined.db from FaultFree + Faulty source databases.

Samples 50 simulationruns per fault to keep DB manageable (~750K rows).

Usage:
    python scripts/build_tep_combined_db.py
"""
import sqlite3
import os
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_FREE   = os.path.join(BASE, "tep_database_FaultFree.db")
SRC_FAULTY = os.path.join(BASE, "tep_database_Faulty.db")
DST        = os.path.join(BASE, "tep_combined.db")
RUNS_PER_FAULT = 50  # keep manageable; full dataset has 500 runs per fault

if os.path.exists(DST):
    os.remove(DST)
    print(f"Removed existing {DST}")

# Read source schema dynamically
_src = sqlite3.connect(SRC_FREE)
_src_cols = _src.execute("PRAGMA table_info(process_data)").fetchall()
N_COLS = len(_src_cols)
col_defs = ", ".join(f"{c[1]} {c[2]}" for c in _src_cols)
_src.close()
print(f"Source schema: {N_COLS} columns")
PLACEHOLDERS = "(" + ",".join(["?"] * N_COLS) + ")"

dst = sqlite3.connect(DST)
dst.execute("PRAGMA journal_mode=WAL")
dst.execute("PRAGMA synchronous=NORMAL")
dst.execute("PRAGMA cache_size=-262144")  # 256MB cache

dst.execute(f"CREATE TABLE process_data ({col_defs})")

dst.execute("""
CREATE TABLE fault_descriptions (
    faultnumber INTEGER,
    description TEXT
)
""")

# Copy fault_descriptions from FaultFree (has all 21 entries)
free = sqlite3.connect(SRC_FREE)
rows = free.execute("SELECT faultnumber, description FROM fault_descriptions ORDER BY faultnumber").fetchall()
dst.executemany("INSERT INTO fault_descriptions VALUES (?,?)", rows)
free.close()
print(f"Copied {len(rows)} fault descriptions")

# Copy FaultFree (IDV=0) — all 250K rows
t0 = time.time()
free = sqlite3.connect(SRC_FREE)
chunk = free.execute("SELECT * FROM process_data WHERE faultnumber=0").fetchall()
dst.executemany(f"INSERT INTO process_data VALUES {PLACEHOLDERS}", chunk)
free.close()
print(f"IDV=0 (normal): {len(chunk):,} rows in {time.time()-t0:.1f}s")

# Copy Faulty (IDV 1-20), 50 runs per fault
faulty = sqlite3.connect(SRC_FAULTY)
total_faulty = 0
for fault_id in range(1, 21):
    t0 = time.time()
    # Get first RUNS_PER_FAULT distinct simulationruns for this fault
    runs = faulty.execute(
        "SELECT DISTINCT simulationrun FROM process_data WHERE faultnumber=? ORDER BY simulationrun LIMIT ?",
        (fault_id, RUNS_PER_FAULT)
    ).fetchall()
    run_ids = tuple(r[0] for r in runs)
    placeholders = ",".join(["?"]*len(run_ids))
    rows = faulty.execute(
        f"SELECT * FROM process_data WHERE faultnumber=? AND simulationrun IN ({placeholders})",
        (fault_id, *run_ids)
    ).fetchall()
    dst.executemany(f"INSERT INTO process_data VALUES {PLACEHOLDERS}", rows)
    total_faulty += len(rows)
    print(f"  IDV={fault_id:2d}: {len(rows):,} rows ({len(run_ids)} runs) in {time.time()-t0:.1f}s")

faulty.close()
print(f"\nTotal fault rows: {total_faulty:,}")

# Indexes for DE query patterns
print("\nBuilding indexes...")
t0 = time.time()
dst.execute("CREATE INDEX idx_fault ON process_data(faultnumber)")
dst.execute("CREATE INDEX idx_fault_run ON process_data(faultnumber, simulationrun)")
dst.execute("CREATE INDEX idx_fault_sample ON process_data(faultnumber, sample)")
dst.commit()
print(f"Indexes built in {time.time()-t0:.1f}s")

# Final stats
cur = dst.cursor()
cur.execute("SELECT faultnumber, COUNT(*) FROM process_data GROUP BY faultnumber ORDER BY faultnumber")
rows = cur.fetchall()
print("\nFinal distribution:")
for r in rows:
    print(f"  IDV={int(r[0]):2d}: {r[1]:,} rows")
cur.execute("SELECT COUNT(*) FROM process_data")
total = cur.fetchone()[0]
print(f"\nTotal: {total:,} rows")
size_mb = os.path.getsize(DST) // 1024 // 1024
print(f"DB size: {size_mb} MB")
dst.close()
print("\nDone: tep_combined.db ready")
