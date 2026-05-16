"""
Rewrite all flat-module imports to new package-qualified imports.

Handles:
  import X                     ->  from PACKAGE import X   (only if X is a relocated module)
  from X import Y              ->  from PACKAGE.X import Y
  from X import (Y,\n  Z)     ->  from PACKAGE.X import (Y,\n  Z)

Usage:
  python fix_imports.py [--dry-run]
"""

import re
import sys
from pathlib import Path

# ── relocation map ──────────────────────────────────────────────────────────
RELOCATIONS: dict[str, str] = {
    # core
    'common': 'core', 'context_assembler': 'core', 'llm_harness': 'core',
    'llm_cache': 'core', 'harness_callback': 'core', 'structured_outputs': 'core',
    'prompt_builder': 'core', 'prompts': 'core', 'judge': 'core',
    'metrics': 'core', 'run_logger': 'core', 'tee_logs': 'core',
    # agents
    'bb_tools': 'agents', 'supervisor_workflow': 'agents', 'supervisor_tools': 'agents',
    'router': 'agents', 'delegate_tools': 'agents', 'subagent_contracts': 'agents',
    'me_workflow': 'agents', 'me_tools': 'agents', 'me_docs': 'agents',
    'de_workflow': 'agents', 'de_tools': 'agents', 'ds_workflow_s2': 'agents',
    'ds_tools': 'agents',
    # knowledge
    'neo4j_kg': 'knowledge', 'tep_knowledge': 'knowledge',
    # simulation
    'stream_simulator': 'simulation', 'file_watcher': 'simulation',
    'diagnose_flow': 'simulation',
}

ROOT = Path(__file__).parent
DRY_RUN = '--dry-run' in sys.argv

# ── regex patterns ───────────────────────────────────────────────────────────
# Pattern A: bare  "import X"  (possibly  "import X as Y")
#   Captures the module name (group 1) and optional alias (group 2)
#   Only when the module is a top-level identifier (no dots).
PAT_BARE_IMPORT = re.compile(
    r'^(\s*)import\s+([A-Za-z_][A-Za-z0-9_]*)(\s+as\s+\w+)?\s*$',
    re.MULTILINE,
)

# Pattern B: "from X import ..."  where X has no dot (flat module)
PAT_FROM_IMPORT = re.compile(
    r'^(\s*)from\s+([A-Za-z_][A-Za-z0-9_]*)\s+import\s+',
    re.MULTILINE,
)


def rewrite_content(src: str) -> tuple[str, int]:
    """Return (new_src, change_count)."""
    changes = 0

    # ── Pass 1: bare `import X` ─────────────────────────────────────────────
    def replace_bare(m: re.Match) -> str:
        nonlocal changes
        indent = m.group(1)
        mod = m.group(2)
        alias = m.group(3) or ''
        if mod not in RELOCATIONS:
            return m.group(0)
        pkg = RELOCATIONS[mod]
        # `import foo` → `from core import foo` (preserve alias if present)
        new_line = f'{indent}from {pkg} import {mod}{alias}'
        changes += 1
        return new_line

    result = PAT_BARE_IMPORT.sub(replace_bare, src)

    # ── Pass 2: `from X import ...` ─────────────────────────────────────────
    def replace_from(m: re.Match) -> str:
        nonlocal changes
        indent = m.group(1)
        mod = m.group(2)
        if mod not in RELOCATIONS:
            return m.group(0)
        pkg = RELOCATIONS[mod]
        new_prefix = f'{indent}from {pkg}.{mod} import '
        changes += 1
        return new_prefix

    result = PAT_FROM_IMPORT.sub(replace_from, result)

    return result, changes


def collect_py_files() -> list[Path]:
    files: list[Path] = []
    for p in ROOT.rglob('*.py'):
        # skip __pycache__ and the script itself
        if '__pycache__' in p.parts:
            continue
        if p.name == 'fix_imports.py':
            continue
        files.append(p)
    return sorted(files)


def main() -> None:
    files = collect_py_files()
    total_changes = 0
    changed_files: list[str] = []

    for fp in files:
        try:
            src = fp.read_text(encoding='utf-8')
        except Exception as e:
            print(f'[SKIP] {fp.relative_to(ROOT)}  ({e})')
            continue

        new_src, n = rewrite_content(src)
        if n == 0:
            continue

        changed_files.append(str(fp.relative_to(ROOT)))
        total_changes += n

        if DRY_RUN:
            print(f'[DRY] {fp.relative_to(ROOT)}  ({n} changes)')
        else:
            fp.write_text(new_src, encoding='utf-8')
            print(f'[OK]  {fp.relative_to(ROOT)}  ({n} changes)')

    print(f'\nTotal: {len(changed_files)} files, {total_changes} import rewrites.')
    if DRY_RUN:
        print('(dry-run — no files written)')


if __name__ == '__main__':
    main()
