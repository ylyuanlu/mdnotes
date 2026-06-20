# Changelog

All notable changes to this project will be documented in this file.

## [v0.1.0] — 2026-06-20

### Added
- **`tag rename` CLI**: `mdnotes tag rename <old> <new>` 支持 dry-run / --force / --ignore-missing / --glob / --exclude
- **Storage `rename_tag_in_file`**: 同时改 frontmatter YAML `tags:` 和 inline `#tag`
- **Storage `scan_and_index_file` add 时索引**: frontmatter + inline tag 双索引
- **CLI `add` 多文件支持**: `mdnotes add file1.md file2.md` (nargs='+')
- **CLI `list` → `ls`**: 避开 Python builtin shadowing (`list` keyword)
- **132 tests**: unit + multi-file 集成 + 边界覆盖

### Technical Decisions
- ADR-0001: dry-run MVP simplified rollback boundary preflight
- ADR-0002: rollback boundary preflight（CLI 层校验 before storage 层执行）

### Test Coverage
- 132 tests pass（task 3 v2 第 6 次尝试通过）
- Ruff: zero errors

## [v0.1.0-mvp] — 2026-06-18

### Added
- **CRUD CLI**: `add`, `list`, `show`, `delete` commands via Click 8
- **SQLite storage**: notes persisted in `~/.mdnotes.db` with WAL journal mode
- **`list --search`**: LIKE-based substring search across title + content
- **TDD test suite**: 62 tests covering core + supplementary scenarios (81% coverage)

### Changed
- Project structure: `src/mdnotes/{cli,storage,render}.py`
- Ruff linter pass with zero errors

### Technical Decisions
- ADR-0001: Markdown renderer (html2text pipeline)
- ADR-0002: SQLite WAL journal mode for concurrency
- ADR-0003: DB path `~/.mdnotes.db` (user-level, not repo-level)

## [v0.1.1] — 2026-06-19

### Added
- **`count` sub-command**: `mdnotes count` 输出 active notes 数量（`Total notes: N`）
- **auto-init behavior**: 无 DB 时自动初始化（`CREATE TABLE IF NOT EXISTS`）
- **`deleted_at` 字段**: v0.2 soft-delete 预留接口（`WHERE deleted_at IS NULL`）
- **PRD/SPEC/ADR-0004**: count sub-command 完整产品 + 技术文档

### Changed
- `tests/test_render.py` / `tests/test_storage.py`: 删除 unused import + variable

### Technical Decisions
- ADR-0004: count SQL 预埋 `deleted_at IS NULL` 条件，为 v0.2 soft-delete 预留接口（方案 B：惰性迁移）

### Test Coverage
- 70 tests pass (前 62 + count-specific 8)
- Coverage: 80% (硬门禁)
- Ruff: 全绿

## [v0.5-stage-close] — 2026-06-20

### v0.5 阶段收尾工作（在 main 上落地）

**v0.5 阶段 = 工作流方案验证阶段，正在收尾**（不是封版，是 v0.5 阶段工作落到 main 上）

### mdnotes 项目版本（验证载体）
- 主分支合并 feature/v0.1.1（count sub-command）
- 当前 main HEAD：v0.1.1（含 70 tests + 80% coverage + ruff 全绿）
- 项目内 tag：v0.1.0-mvp + v0.1.1（mdnotes 项目自身 release tag）

### v0.5 阶段里程碑（在 main 上的产物）
- 软强制层（sub-agent 框架）
- 8 状态机（debating → done + 6 failed 子状态）
- 6 gate 验证（task-status / status-transition / review-report / test-report × schema + critical + coverage）
- 决策 5 重新定义（飞书多 bot outbound 弃用）
- 验证载体 mdnotes：task 1 + task 2 端到端跑通
- merge feature/v0.1.1 → main

### 工作流框架（v0.5 阶段当前状态）
- 6 role agent：main / pm / architect / dev / reviewer / qa / devops
- 4 debate sub-agent：product-champion / tech-reviewer / devil-advocate / quality-gatekeeper
- 4 个 6 gate 验证脚本：兼容 `## field` 标题 + `field:` 单行两种格式
- 9 个 templates：PRD / SPEC / DECISIONS / debate-log / review-report / test-report / context-summary / task.json / feedback.json / project.json
- PM AGENTS.md §2/§2.1：Round 3 触发器 + session 重启容忍
- main AGENTS.md 跨平台兼容：sessions_yield 等 push 事件

### 飞书多 bot 基础设施
- 11 个 bot app + 11 个 bindings（main/pm/architect/dev/reviewer/qa/devops/sre/content/support）
- 决策 5 重新定义：bot 基础设施就位（不指望 sub-agent / agent 顶级 session 自动 outbound）

### v0.5 阶段收尾 = 进入 v1.0 阶段的实施方案
- v0.5 阶段还在进行中（"0.5 不是刚要完成吗"）
- v0.5 阶段收尾 = 为 v1.0 阶段准备实施方案（不是发布 v1.0，不是封版 v0.5）
- v1.0 阶段 = v0.5 收尾后的下一阶段（实施方案待主公定稿）

### 下一步（独立动作）
- mdnotes task 3（v0.2 soft-delete）= mdnotes 项目自己的下一步动作（项目层，不是框架层）
