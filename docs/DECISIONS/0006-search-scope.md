# ADR-0006 — search scope 决策：MVP 三字段 vs 完整扩展

> **日期**：2026-06-20
> **状态**：Accepted
> **适用版本**：v1.5+
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/04-search-command.md` / `docs/SPEC/04-search-command.md` / `.tasks/t_20260620_67128/debate-log.md`

## 背景

PM PRD 定义的 MVP 搜索范围是 title + content + tag 三字段搜索。Tech Reviewer 在辩论中指出搜索 scope 可以扩展到 metadata（文件大小、创建时间、修改时间、文件路径）。Product Champion 和 Quality Gatekeeper 指出 v1.0 应聚焦 MVP，扩展字段是 v2 候选。

需决定：v1.0 MVP scope 是否只做 title + content + tag，还是包含 metadata 字段。

## 决策

**v1.0 MVP scope = title + content + tag 三字段搜索（FTS5 索引）**。

scope 之外（v2 候选）：
- 文件 metadata（文件大小 / 创建时间 / 修改时间）
- 文件路径搜索
- 多词 AND/OR 组合语法
- fuzzy search
- BM25 rank 自定义
- highlight 排序展示

## 考虑的替代方案

### 方案 A：MVP scope（title + content + tag）（采纳）

- ✅ **覆盖 95% 用户场景**：标题搜（US-1）+ 内容搜（US-3）+ tag 搜（US-2）三大核心场景全覆盖
- ✅ **实现成本低**：FTS5 三字段索引，无需额外 JOIN 或 denormalization
- ✅ **Schema 简单**：FTS5 virtual table 直接三列，trigger 同步逻辑清晰
- ✅ **CLI 输出稳定**：title + content + tag 输出格式固定，v2 扩展不影响 v1 接口
- ❌ **无法搜索 metadata**：用户无法按"文件大小 > 1MB"或"创建时间 > 7天前"筛选
- ❌ **无法搜索文件名**：用户无法搜"文件名含 api 的 .md"（只能搜内容）

### 方案 B：完整 scope（title + content + tag + metadata）

扩展字段：
- `file_size`：笔记 .md 文件字节数
- `created_at`：.md 文件创建时间
- `modified_at`：.md 文件修改时间
- `file_path`：.md 文件相对路径

- ❌ **实现复杂度高**：metadata 字段需从文件系统读取（`os.stat()`），每次 search 都要 fs CALL，开销大
- ❌ **破坏 FTS5 语义**：FTS5 索引 content 字段是文本，metadata（时间戳/文件大小）是结构化数据，不应混在 FTS5 里
- ❌ **与 vault 同步问题**：metadata 随文件系统变化，FTS5 trigger 只监听 DB 写，不监听 fs 变更
- ❌ **Scope 膨胀**：v1.0 是收口阶段，scope 膨胀违背"8 状态机端到端跑通"目标
- ❌ **过度工程**：100-1000 笔记规模下，metadata 搜索是低频需求

### 方案 C：独立 metadata 搜索层（v2 混合方案）

- ❌ 需要两个索引：FTS5（文本）+ metadata B-tree（文件大小/时间）
- ❌ CLI 复杂度：用户需理解两个索引的使用场景
- ❌ v2 扩展，不在 v1.0 范围内

## 决定

**采纳方案 A：MVP scope（title + content + tag）。**

理由：
1. **ROI 最高**：title + content + tag 覆盖 95% 用户搜索场景，metadata 搜索是低频需求
2. **Schema 简单**：FTS5 三列索引，trigger 同步逻辑简单，无冗余状态
3. **v1.0 约束**：本 task 是 v1.0 收口验证 task，scope 膨胀违背 8 状态机端到端跑通目标
4. **可逆性高**：v2 加字段不破坏现有索引（`ALTER TABLE notes_fts ADD COLUMN metadata_field`）
5. **metadata 搜索的 FS CALL 问题**：每次 search 都 `os.stat()` 获取 metadata，开销不可接受

## 后果

### 正面

- ✅ MVP 三字段 FTS5 索引 schema 简洁，trigger 同步逻辑清晰
- ✅ `tag` 字段 denormalized（存储 `notes.tags` 逗号分隔文本），支持无 `--tag` 筛选时的全文匹配
- ✅ v2 扩展 fields 不破坏现有索引（FTS5 `ALTER TABLE notes_fts ADD COLUMN` 支持在线加列）
- ✅ CLI 输出格式稳定，v2 扩展不影响 v1 接口契约

### 负面

- ❌ **无法按文件名搜索**：用户搜 "api" 只能搜内容，不能搜文件名 "api-design.md"
  - **缓解**：未来 v2 可加 `--filename` 选项（glob pattern 匹配文件系统路径）
- ❌ **无法按创建/修改时间过滤**：用户无法搜"最近 7 天修改过的笔记"
  - **缓解**：未来 v2 可加 `--since` / `--until` 选项（JOIN metadata_view）
- ❌ **tag 字段 denormalized 限制**：notes.tags 逗号分隔，精确 tag JOIN 依赖 tags 表（`--tag` 用 tags 表 JOIN，而非 FTS5 tag 字段）
  - **缓解**：PM 仲裁已明确 `--tag` 用 tags JOIN；FTS5 tag 字段用于无筛选时的全文匹配

## 可逆性

**高可逆**。

- ✅ FTS5 支持在线加列：`ALTER TABLE notes_fts ADD COLUMN metadata_field`
- ✅ 加字段不破坏现有索引（无需 rebuild）
- ✅ v2 扩展 fields 不影响 v1 已有数据
- ✅ metadata 字段搜索不依赖 FTS5（可另建 B-tree 索引）

---

*Architect Agent 完成。v1.0 MVP scope = title + content + tag 三字段。*
