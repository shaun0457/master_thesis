# Session Progress

Read this after `AGENTS.md` and `WORKSPACE_INDEX.md` when starting a new session.

## Purpose

This file is the short-horizon working memory for active development in `MT-phase-2`.

Use it for:

- what was just finished
- what is currently true
- what should happen next
- blockers, assumptions, and temporary decisions

Do not use it for long-term architecture explanation. That belongs in:

- [CODEx_MEMORY.md](./CODEx_MEMORY.md)
- [WORKSPACE_INDEX.md](./WORKSPACE_INDEX.md)
- [AGENTS.md](./AGENTS.md)

## Current Status

- Regression baseline: `pytest tests/ -q → 85 passed` (2026-05-14, commit b2af005)
- Live evaluation baseline: `9/9 PASS` (2026-05-13)
- 4 CODEX_REVIEW findings resolved and committed (see below)

## Current Phase

Phase: production hardening — CODEX_REVIEW fixes complete

## Completed Recently (2026-05-14)

- **bb_tools.py**: renamed Python helper to `_write_to_blackboard_impl`；消除 @tool 同名覆蓋導致的遞迴失敗
- **de_tools.py**: 查詢無 LIMIT 時自動注入 `LIMIT {DE_MAX_ROWS}`（預設 10000）；更新 import
- **router.py**: `_consume_p2p_requests` 子委派前加 `_metrics_lock` 節流計數，關閉 P2P 繞過漏洞
- **tests/conftest.py**: 硬編碼路徑換成 `tmp_path_factory.mktemp()`，CI 可攜
- 封存舊 MD 文件、舊 prompt cards、舊 PNG plots（commit 1217510）

## Current Working Assumptions

- 無已知阻斷問題；下一輪優先從 eval / 論文寫作方向選
- `archive/` 僅供歷史參考，不影響 bootstrap

## Next Recommended Step

1. 決定下一個工作軌道：(a) eval 深化、(b) 論文分析、(c) 繼續 production hardening
