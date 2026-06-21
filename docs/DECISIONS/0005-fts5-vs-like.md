# ADR-0005 — FTS5 vs LIKE 全文搜索技术选型

> **日期**：2026-06-20
> **状态**：Accepted
> **决策者**：Architect Agent（PM 仲裁后采纳）
> **相关文档**：`docs/PRD/04-search-command.md` / `docs/SPEC/04-search-command.md` / `.tasks/t_20260620_67128/debate-log.md`

## 背景

mdnotes v1.0 需要实现 `mdnotes search <query>` 全文搜索。Devil Advocate 在 3 轮辩论中主张 MVP 阶段用 SQLite `LIKE '%query%'`（成本低、无额外 schema），Product Champion 和 Tech Reviewer 主张直接上 FTS5（性能差距 5-30x，内容搜索无索引不可接受）。

PM 最终仲裁：**采用 FTS5**（否决 LIKE MVP 方案）。

## 决策

**采用 SQLite FTS5 全文索引，不提供 LIKE fallback。**

FTS5 schema：`content='notes'` 关联型 + `unicode61` tokenizer + 3 个 trigger 自动同步。

## 考虑的替代方案

### 方案 A：LIKE '%query%' MVP 方案（Devil Advocate 主张）

- ✅ 实现简单：无需 virtual table、无需 trigger、无需 schema 迁移
- ✅ 无额外同步维护：直接查 `notes` 表，无 FTS5 与 notes 表一致性问题
- ✅ 用户熟悉度：LIKE 是 SQL 标准，运维/调试无学习成本
- ❌ **性能差距 5-30x**（1000 笔记 P95 > 1000ms）：LIKE on content TEXT 无索引，全表扫描 I/O 成本高
- ❌ **中文支持差**：LIKE `'%中文%'` 在 SQLite 中文分词下准确性低，连续词匹配行为不符合用户预期
- ❌ **无相关性排序**：LIKE 无 BM25 评分，所有结果无差别排序，用户体验差
- ❌ **无法实现 tag rename 预演**（US-2）：LIKE 只能搜 content/title，不能 JOIN tags 做精确 tag 筛选

### 方案 B：FTS5 全文索引（采纳）

- ✅ **性能：P95 ≤ 100ms（1000 笔记）**：FTS5 专用索引，内容搜索亚毫秒响应
- ✅ **中文 / Unicode 支持**：unicode61 tokenizer 是唯一可行的中文分词方案
- ✅ **相关性排序**：BM25 评分，相关性高的结果优先
- ✅ **支持 tag 筛选**：JOIN tags 表做精确 tag_name 筛选，支持 US-2（tag rename 预演）
- ✅ **FTS5 MATCH 语法**：支持字段前缀搜索 `title:python`，精确控制搜索范围
- ❌ **Schema 复杂度**：virtual table + 3 个 trigger（INSERT/UPDATE/DELETE）+ rebuild 命令 ≈ 200 行代码
- ❌ **同步维护负担**：trigger 同步可能不一致（statement-level trigger 批量 update 限制已通过 warning 缓解）
- ❌ **FTS5 模块依赖**：需 Python 3.14 + SQLite 3.46.1+，精简版 Python 可能不带 FTS5（已通过 CI fail-fast + README 明确依赖缓解）

### 方案 C：外部搜索引擎（Elasticsearch / Whoosh）

- ❌ **引入外部依赖**：违背 mdnotes "零外部依赖" 原则
- ❌ **运维复杂度**：需单独服务，违背本地 CLI 工具定位
- ❌ **过度工程**：MVP 阶段 100-1000 笔记规模不需要外部搜索引擎

## 决定

**采纳方案 B：FTS5 全文索引。**

理由（PM 仲裁）：
1. 内容搜索场景（US-3）：LIKE on content TEXT 无索引，5000 条下比 FTS5 慢 5-30 倍，不可接受
2. title 搜索：LIKE 够用，但为统一技术架构和 trigger 同步，FTS5 更简单
3. tag rename 后 FTS5 同步更新是关键用户体验（US-2），LIKE 无法实现
4. v1.0 锁定期需要端到端验证 FTS5 能力，不能用 LIKE 换皮

**关键约束（PM 仲裁条件）：**
- CLI query 预处理必须实现（AND/OR 语义）
- unicode61 tokenizer 必须使用（中文支持）
- FTS5 CI fail-fast（不允许 skip 或 fallback）
- 文档明确说明引号语义和特殊字符转义

## 后果

### 正面

- ✅ P95 ≤ 100ms（1000 笔记）性能门禁可达成
- ✅ 中文内容搜索用户体验正常
- ✅ BM25 相关性排序，结果质量高
- ✅ tag rename 预演（US-2）可实现
- ✅ FTS5 索引在 add/delete/update 后自动同步（trigger）

### 负面

- ❌ **FTS5 模块依赖**：非所有 Python 环境可用（精简版 SQLite / 移动端 Python）
  - **缓解**：m920x 验证可用；CI 要求 FTS5 环境；README 明确 Python 3.14 + SQLite 3.46.1+ 依赖
  - **不可用时**：CLI 报错 "FTS5 not available"，exit code 2，不降级
- ❌ **statement-level trigger 批量 update 限制**：tag rename 影响多条时只同步最后一条
  - **缓解**：> 10 条时 warning；auto-check 发现不一致时提示 rebuild
- ❌ **Schema 迁移复杂度**：需新增 `id` integer 列映射 rowid（UUID 保留）
  - **缓解**：惰性迁移（首次 search 时触发），幂等 `ALTER TABLE`
- ❌ **rebuild 命令**：在线 rebuild 实现复杂（ALTER TABLE RENAME 原子替换）
  - **缓解**：rebuild 期间旧索引表服务，无 downtime

## 可逆性

**中等可逆**。

- ✅ FTS5 删除成本低：`DROP TABLE notes_fts` + `DROP TRIGGER notes_ai/au/ad` 即可移除
- ✅ 删除后 notes 表数据不受影响（content= 关联型，FTS5 不冗余存储）
- ✅ 可在 v2 阶段切换回 LIKE（或混合方案），不影响已有笔记
- ❌ **数据层不可逆**：现有笔记的 `id` integer 列已添加，不可回退（但无害）
- ❌ **重新索引成本**：从 LIKE 切回 FTS5 需重建索引（`--rebuild`）

---

*Architect Agent 完成。PM 仲裁已执行。*
