# ADR-0002 — SQLite Journal 模式选型

> **日期**：2026-06-18
> **状态**：Accepted
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/01-cli-mvp.md` / `docs/SPEC/01-cli-mvp.md`

## 背景

SQLite 支持多种 journal 模式（rollback WAL / WAL / MEMORY / OFF），影响：
- **并发安全性**：多进程同时写入时是否触发 `database is locked`
- **写入性能**：单次写入延迟和磁盘 I/O
- **崩溃恢复**：系统崩溃后数据是否能恢复

PRD 技术约束：
- 并发写入：`database is locked` 最多重试 3 次（100ms / 200ms / 400ms 指数退避）
- WAL 模式评估触发条件：并发冲突率 > 1%

Tech Reviewer Round 3 结论：默认 rollback journal；WAL 按需评估。

## 决策

**MVP 默认使用 rollback journal（WAL off），不主动开启 WAL 模式**。

## 考虑的替代方案

### 方案 A：默认 rollback journal（采纳）

- ✅ Python `sqlite3` 默认行为，零配置
- ✅ 单进程写入完全安全
- ✅ 崩溃后自动恢复（rollback journal 机制）
- ✅ 对单用户 CLI 工具足够（并发冲突率 << 1%）
- ❌ 多进程并发写入时锁冲突概率高于 WAL

### 方案 B：默认开启 WAL 模式

```python
conn.execute("PRAGMA journal_mode=WAL")
```
- ✅ 多进程并发读取时无锁（读不阻塞写）
- ✅ 写入锁冲突比 rollback journal 少
- ❌ 需要额外理解 WAL checkpoint 机制
- ❌ 单进程 MVP 场景无收益，反而增加复杂性
- ❌ WAL 文件（`-wal` + `-shm`）需要额外清理逻辑

### 方案 C：默认开启 WAL + 显式 checkpoint

- 在每次 `add/delete` 后执行 `PRAGMA wal_checkpoint(TRUNCATE)`
- ✅ WAL 优点全保留
- ✅ 防止 WAL 文件无限增长
- ❌ MVP 阶段过度设计（WAL 文件增长问题在 500 条笔记内不明显）
- ❌ checkpoint 增加每次写入延迟

## 决定

**采纳方案 A：默认 rollback journal，WAL 作为 P2 监控后的优化选项**。

理由：单用户 CLI 工具的并发写入概率极低（几乎只有脚本批量导入场景），rollback journal 完全满足需求。WAL 模式适合多进程读密集场景，MVP 不需要。并发冲突率监控（P2）触发 > 1% 后，ADR 另行升级。

## 后果

### 正面

- ✅ 零配置，与 Python sqlite3 默认行为一致
- ✅ 崩溃恢复有保障
- ✅ 实现简单，storage.py 无需管理 WAL 文件生命周期

### 负面

- ❌ 脚本批量并发 add（如 `for i in {1..100}; do mdnotes add "批量笔记 $i" & done`）可能触发 `database is locked`
  - **缓解**：重试 3 次 + 指数退避；幂等性保证重复执行安全
  - **升级条件**：DoD-8 并发测试 deadlock 率 > 5% 时，升级本 ADR 评估 WAL
- ❌ rollback journal 在写入期间排斥其他读取（读也会被阻塞）
  - **影响**：对单用户可忽略（交互式 CLI 不会边写边读）

### P2 触发条件（监控指标）

- 并发 10 进程 add 冲突率 > 1% → 评估 WAL 模式升级
- WAL 文件大小超过 `notes.db` 本身大小 3 倍 → 评估 checkpoint 策略
