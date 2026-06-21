# search 优化 - 产品需求文档

> **Task ID:** t_20260621_v150_032907
> **适用版本**: v1.5.0+
> **模块编号:** 06
> **作者:** PM Agent
> **创建时间:** 2026-06-21T09:08:27+08:00
> **辩论轮次:** 3 轮（product-champion / tech-reviewer / devil-advocate / quality-gatekeeper）
> **PRD 状态:** spec-ready

---

## 1. 任务一句话

实现 mdnotes v1.5 search 优化：tag 组合搜索（`--tag` 多个 AND/OR）、snippet 高亮（ANSI 终端兼容），提升搜索精度和结果可读性——让 mdnotes 用户在 500+ 笔记时仍能快速定位目标内容。

---

## 2. 用户故事

### US-1：组合 tag 精准定位
> 作为使用 tag 分类笔记的用户，我需要 `search "performance" --tag python --tag dev` 找到同时有 python 和 dev tag 的笔记——这样 tag 系统从"分类"升级为"多维检索"，我能跨维度精确定位。

**验收标准：**
- `mdnotes search "keyword" --tag a --tag b` 返回同时含 tag a 和 tag b 且 content 匹配 keyword 的笔记（AND 语义）
- `mdnotes search "keyword" --tag a --tag b --or` 返回含 tag a 或 tag b 且 content 匹配 keyword 的笔记（OR 语义）
- exit code 0（有结果）或 1（无结果）

### US-2：搜索结果一眼定位
> 作为在 500+ 笔记中搜索的用户，我需要 snippet 高亮让我在结果列表中一眼看到关键词出现在哪里——减少无效打开，结果页即决策页。

**验收标准：**
- `mdnotes search "performance"` 结果中关键词被 `<mark>` 标签包裹
- CLI 输出时 `<mark>` 转换为 ANSI escape code（粗体或高亮色）
- `--color=auto|always|never` 控制颜色输出

### US-3：中文搜索降级提示
> 作为中文用户，我用 `mdnotes search "性能优化"` 搜索，当前阶段（trigram v1.6 实现前）我收到友好提示，告诉我这是已知局限——而不是静默返回空结果或错误。

**验收标准：**
- 当搜索词含 CJK 字符且不带精确引号，返回结果时附带提示："中文模糊搜索已计划在 v1.6 实现，当前请使用精确匹配"
- 搜索功能本身正常工作（unicode61 tokenize 按字符匹配）
- HTTP 200，不报错

---

## 3. 业务流程

```
用户输入: mdnotes search "performance" --tag python --tag dev
    │
    ▼
[1] CLI 参数解析
    - query 必填
    - --tag 可重复（多次出现）
    - --or 切换组合语义（默认 AND）
    - --color=auto|always|never（默认 auto）
    - --limit N（默认 100）
    │
    ▼
[2] Tag 组合构建
    ┌─ AND（默认）：SELECT note_id FROM tags WHERE tag_name IN ('python','dev') GROUP BY note_id HAVING COUNT(*) = N
    └─ OR（有 --or）：SELECT note_id FROM tags WHERE tag_name IN ('python','dev') GROUP BY note_id
    │
    ▼
[3] FTS5 搜索
    SELECT n.* FROM notes n
    JOIN notes_fts ON n.id = notes_fts.id
    JOIN (tag_subquery) t ON n.id = t.note_id
    WHERE notes_fts MATCH ?
    AND n.deleted_at IS NULL
    ORDER BY rank
    LIMIT N
    │
    ▼
[4] Snippet 高亮
    snippet(notes_fts, 2, '<mark>', '</mark>', '...', 32)
    │
    ▼
[5] CLI 格式化
    - 文件路径 + 标题 + snippet
    - <mark> → ANSI escape code（--color=always）
    - --color=auto 时 terminal 直出颜色，pipe less 时提示 less -R
    │
    ▼
[6] Exit Code
    - 0：有结果
    - 1：无结果
    - 2：系统异常（FTS5 语法错误 / 数据库锁定）
```

---

## 4. 业务价值 / ROI

### 解决的问题
- tag 孤岛问题：单 tag 搜索不够用，实际场景需要"同时有 tag A 和 tag B"
- 结果可读性差：纯文本结果列表，用户需要逐条打开才能判断相关性
- 中文搜索质量：unicode61 对中文分词能力有限，模糊搜索效果差

### 预期收益
| 维度 | 现状 | search 优化后 |
|------|------|--------------|
| 组合搜索 | 不支持（单 tag 搜索）| AND/OR 组合，精准定位 |
| 结果可读性 | 纯文本列表 | snippet 高亮，一眼定位 |
| 搜索效率 | 逐条打开判断相关性 | 结果页即决策页 |
| 中文搜索 | unicode61 字符匹配 | v1.6 trigram 提升模糊匹配 |

### ROI 估算
- **开发成本：** 8-12 小时（tag index + AND/OR SQL + snippet 高亮 + CLI 格式化 + 测试）
- **用户收益：** 搜索是高频操作（仅次于 add/list），每次搜索省 30 秒
- **ROI 节点：** 用户上手第一天即回本（每天节省 1-2 分钟）

### 优先级
**P1（v1.5 必须）**：tag AND/OR + snippet 高亮
**v1.6（不在本 PRD）**：中文 trigram 优化

---

## 5. 范围边界

### MVP 包含（v1.5）
- `search --tag a --tag b`（AND 语义，默认）
- `search --tag a --tag b --or`（OR 语义）
- `--tag` 可重复（`--tag a --tag b --tag c`）
- snippet 高亮（`<mark>` 标签，ANSI 颜色）
- `--color=auto|always|never`
- `--limit N`（默认 100）
- 中文搜索降级提示（BC-17）
- `idx_tags_name` 索引（性能关键）

### v1.6 后续（不在本 PRD 范围）
- 中文 trigram 优化（SQLite 3.27+）
- 搜索结果分页（`--page N`）
- 日期过滤（`--since YYYY-MM-DD`）
- 模糊匹配（fuzzy search）
- BM25 rank 自定义权重

### 明确不做
- 非 ANSI 终端的纯文本 fallback（v1.6 考虑）
- 多语言混排的 trigram 优化（v1.6 trigram）
- 搜索结果导出（v2.0）

---

## 6. 验收标准

### 功能验收
- [ ] `mdnotes search "keyword" --tag a --tag b` 只返回同时含 tag a 和 tag b 且 MATCH keyword 的笔记
- [ ] `mdnotes search "keyword" --tag a --tag b --or` 返回含 tag a 或 tag b 且 MATCH keyword 的笔记
- [ ] `mdnotes search "keyword"`（无 --tag）正常工作（不退化）
- [ ] `mdnotes search "keyword" --tag a --tag b --tag c`（3 个 tag AND）正常工作
- [ ] snippet 中关键词被 `<mark>` 标签包裹
- [ ] `--color=always` 时输出 ANSI escape code
- [ ] `--color=auto` 时 terminal 直出颜色，pipe less 时不输出颜色代码
- [ ] `--color=never` 时不输出颜色代码
- [ ] 结果超过 100 条时截断，输出"显示前 100 条，共 N 条"
- [ ] 无结果时 exit code 1，友好提示"未找到匹配笔记"
- [ ] 含 CJK 字符且不带引号的搜索返回友好提示（BC-17）

### 同步验收
- [ ] `mdnotes add` 新笔记后立即 search 能搜到
- [ ] `mdnotes delete`（软删除）后立即 search 不返回已删除笔记
- [ ] `mdnotes restore` 后立即 search 能重新搜到该笔记
- [ ] tag rename 后 search --tag 新名称立即生效

### 性能验收
- [ ] tag AND 查询 P95 ≤ 200ms（1000 笔记，冷缓存）
- [ ] tag OR 查询 P95 ≤ 200ms（1000 笔记，冷缓存）
- [ ] 50 并发搜索请求 P95 ≤ 500ms（BC-16，非阻断性监控指标）
- [ ] `idx_tags_name` 索引存在且被查询计划命中

### 维护验收
- [ ] `mdnotes search --check` 返回索引健康状态
- [ ] FTS5 语法错误时报错 "FTS5 syntax error"，exit code 2
- [ ] `mdnotes search`（无 query）时报错 "用法：mdnotes search <query>"，exit code 2

### 质量验收
- [ ] `mdnotes search --help` 包含所有新参数说明
- [ ] 覆盖率：单元 ≥ 90%，整体 ≥ 86%，新增代码 ≥ 90%
- [ ] 覆盖率环比不下降 > 1%（BC-13）
- [ ] Python 3.10/3.11/3.12 三个版本 GHA CI 均通过

### 风险指标（触发阻断合并）
- [ ] CI 任意一个 Python 版本失败 → 阻断合并
- [ ] 覆盖率跌破 86% → 阻断合并
- [ ] AND/OR 逻辑错误（笛卡尔积）→ 阻断合并
- [ ] 中文搜索返回结果但 snippet 无高亮 → 阻断合并
- [ ] P99 > 500ms → 性能告警（非阻断）

---

## 7. 关键约束（辩论共识）

以下约束来自 3 轮辩论收敛共识：

### 约束 1：AND 是默认语义，OR 通过 --or flag 切换
- `search --tag a --tag b` = AND（同时含 a 和 b）
- `search --tag a --tag b --or` = OR（含 a 或 b）
- 不支持混用 AND/OR（`--tag a AND --tag b OR --tag c` 不支持）
- 不支持括号优先级（`--tag a --tag b --or --tag c` 按从左到右 OR 解析）

### 约束 2：snippet 高亮使用 ANSI escape code
- FTS5 `snippet()` 函数输出 `<mark>` 标签
- CLI 层负责将 `<mark>` 转换为 ANSI escape code（`\x1b[1m` ... `\x1b[0m`）
- `--color=never` 时输出纯文本（`<mark>` 标签保留，不转换）
- 非 ANSI 终端（如 Windows 旧版 cmd）可能显示原始标签（已知局限）

### 约束 3：中文搜索降级提示（BC-17）
- 当搜索词含 CJK 字符且不带精确引号，输出附带提示
- 功能本身正常工作（unicode61 按字符匹配）
- 提示文字："中文模糊搜索已计划在 v1.6 实现，当前请使用精确匹配"

### 约束 4：search 入口过滤 deleted_at
- 所有 search SQL 必须 `WHERE deleted_at IS NULL`（应用层过滤）
- 这依赖 PRD-05 soft-delete 的 `deleted_at` 字段存在
- **技术顺序：PRD-05 先交付，PRD-06 基于已发布 PRD-05 开发**

### 约束 5：tag index 性能关键
- 必须创建 `idx_tags_name` 索引：`CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(tag_name)`
- 无此索引时 tag 组合查询会全表扫描，P95 可能从 1.3ms 升至 10ms+

---

## 8. 风险提示

### 风险 1：AND/OR 优先级歧义（已缓解）
- **描述：** 用户可能期望 `--tag a --tag b --or` 按 AND then OR 解析，但实现是按从左到右 OR
- **缓解：** `--help` 明确说明语义；不支持混用；无括号优先级
- **剩余风险：** 高级用户可能需要优先级，但 v1.5 不支持

### 风险 2：非 ANSI 终端显示（已知局限）
- **描述：** Windows 旧版 cmd、某些 IDE 内嵌终端不支持 ANSI escape code
- **缓解：** `--color=never` 纯文本模式；`--color=auto` 检测终端能力
- **升级条件：** v1.6 考虑纯文本 fallback 或检测库

### 风险 3：tag 数量过多导致 SQL 膨胀（已缓解）
- **描述：** `--tag` 重复 100 次时 SQL 非常长
- **缓解：** `--help` 建议单个笔记 tag 数量 ≤ 20；内部硬限制 50 个 tag（超出报错）
- **升级条件：** v1.6 考虑 tag 数组类型优化

### 风险 4：中文搜索质量差（已知局限，BC-17 缓解）
- **描述：** unicode61 对中文按 Unicode 边界分词，模糊匹配效果不如 trigram
- **缓解：** BC-17 降级提示；v1.6 trigram 实现
- **升级条件：** v1.6 trigram 是 P0 技术债

### 风险 5：search 和 soft-delete 并发（PRD-05 约束覆盖）
- **描述：** search 正在执行时笔记被 delete
- **缓解：** search SQL 加 `WHERE deleted_at IS NULL`；SQLite WAL 模式隔离
- **剩余风险：** 极低（WAL 模式保证 read 不阻塞 write）

---

## 附录：技术决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| tag 组合默认语义 | AND | 最常用场景是"同时满足多个 tag" |
| OR 切换方式 | --or flag | 避免歧义，不支持混用 |
| snippet 高亮 | `<mark>` + ANSI | FTS5 原生支持，ANSI 广泛兼容 |
| 颜色控制 | --color=auto/always/never | 类 grep 惯例 |
| 中文搜索降级 | BC-17 提示，非报错 | 用户体验优于静默失败 |
| tag index | 必须加 | 无 index 全表扫描，P95 劣化 10x |
| search 与 soft-delete | 串行上线 | search 过滤依赖 deleted_at 字段存在 |

---

*PM 辩论收敛完成。SPEC 由 Architect 依据本 PRD 自主撰写。*
