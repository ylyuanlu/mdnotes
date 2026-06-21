# mdnotes search - 产品需求文档

> **Task ID:** t_20260620_67128
> **模块编号:** 04
> **作者:** PM Agent
> **创建时间:** 2026-06-20T22:53:00+08:00
> **辩论轮次:** 3 轮（product-champion / tech-reviewer / devil-advocate / quality-gatekeeper）
> **PRD 状态:** spec-ready

---

## 1. 任务一句话

实现 `mdnotes search <query>` 全文搜索命令，基于 SQLite FTS5 全文索引，支持 title + content + tag 三字段搜索，响应时间 P95 ≤ 100ms（1000 笔记），支持中文和 Unicode。

---

## 2. 用户故事

### US-1：找回失踪笔记
> 作为 mdnotes 用户，我能在忘记文件名时，通过 `mdnotes search "FTS5 配置"` 直接找到包含该关键词的所有笔记，而不必记住标题或日期。

**验收标准：**
- `mdnotes search "FTS5"` 返回所有 title/content/tag 含 "FTS5" 的笔记
- 每条结果显示：文件路径、标题、匹配 snippet（高亮关键词）
- exit code 0（有结果）或 1（无结果）

### US-2：tag rename 前预演
> 作为 mdnotes 用户，rename tag 前我执行 `mdnotes search --tag "v1"` 验证受影响的笔记列表，确认后再执行 rename，避免误操作。

**验收标准：**
- `mdnotes search --tag "v1"` 只返回 tags 表中 tag_name='v1' 的笔记
- `mdnotes tag rename v1 v2` 执行后，`mdnotes search --tag "v2"` 能立即搜到rename后的笔记
- rename 影响超过 10 条时 CLI 输出 warning："FTS5 索引可能不一致，建议运行 mdnotes search --check"

### US-3：内容级快速定位
> 作为技术写作者，我搜索 `mdnotes search "performance"` 找出所有讨论性能的笔记，无需 grep + 手动过滤，享受亚毫秒响应。

**验收标准：**
- `mdnotes search "performance"` 搜索 title + content + tag 三字段（FTS5 MATCH）
- P95 响应时间 ≤ 100ms（1000 笔记，冷缓存）
- 支持中文：`mdnotes search "性能优化"` 能找到包含"性能"和"优化"的笔记

### US-4：组合过滤（v2 候选）
> 作为笔记归档者，我用 `mdnotes search "python" --tag "dev"` 组合搜索 content + tag，精确定位跨维度笔记。

**v1 不做**（v2 候选）：组合搜索的 FTS5 实现复杂度高，MVP 阶段先做单字段搜索。

### US-5：多文件搜索结果
> 作为多项目用户，我搜索 `mdnotes search "api"` 时能看到所有包含 api 的笔记，每个结果行显示文件路径，方便我定位到具体文件。

**验收标准：**
- 多个 .md 文件匹配时，每行显示：`file/path.md: 标题  ...匹配snippet...`
- 文件路径含空格时加引号：`"my notes/test.md"`
- 结果超过 100 条时截断，输出："显示前 100 条，共 N 条"

---

## 3. 业务流程

```
用户输入: mdnotes search "python"
    │
    ▼
[1] CLI 参数解析
    - query 必填（无 query → exit code 2，错误提示）
    - 支持 --tag <name>（可选）
    - 支持 --color=auto|always|never（默认 auto）
    - 支持 --limit N（默认 100）
    │
    ▼
[2] Query 预处理（CLI 层）
    - 无引号 query → FTS5 OR 语义（"python redis" → python OR redis）
    - 有引号 query → FTS5 AND 语义（'"python redis"' → python AND redis）
    - 特殊字符（& | - " *）→ 转义处理
    │
    ▼
[3] FTS5 搜索
    ┌─ 无 --tag：SELECT * FROM notes_fts WHERE notes_fts MATCH '<预处理后query>'
    └─ 有 --tag：JOIN tags WHERE tags.tag_name = ? AND rowid 匹配
    │
    ▼
[4] 结果格式化
    - 文件路径 + 标题 + 匹配 snippet
    - 高亮关键词（ANSI escape code，--color=always）
    - pipe less 时提示用 less -R
    │
    ▼
[5] Exit Code
    - 0：有结果
    - 1：无结果
    - 2：系统异常（FTS5 语法错误 / 数据库锁定 / FTS5 不可用）
```

---

## 4. 业务价值 / ROI

### 解决的问题
- 用户平均找一条笔记需要 2-5 分钟 grep + 人工过滤
- 笔记变成死知识（找不到 = 不会用 → 重复写）
- tag rename 后无法验证影响面，用户不敢用 rename 功能

### 预期收益
| 维度 | 现状 | 搜索后 |
|------|------|--------|
| 找笔记时间 | 2-5 分钟 | < 1 秒 |
| 搜索方式 | grep + 手动过滤 | `mdnotes search "keyword"` |
| tag rename 安全性 | 无法预演 | `search --tag` 预演 |
| 用户信心 | "找不到 = 不知道" | 搜得到 = 笔记可用 |

### ROI 估算
- **开发成本：** 8-12 小时（FTS5 schema + 3 trigger + CLI search 命令 + 测试）
- **用户收益：** 100 用户 × 每周节省 10 分钟 = 每周节省 1000 分钟
- **ROI 节点：** 用户上手第一天即回本
- **与 03-tag-rename 联动：** search 让 rename 有"预览-确认"能力，降低用户风险焦虑，rename 使用率预计提升 50%+

### 优先级
**P0（v1.0 必须）**：search 命令 + FTS5 索引 + 基础边界 case
**P1（v1.0 可选）**：--color 高亮、--check 健康检查
**P2（v2）**：模糊匹配、多词 AND/OR、highlight 排序、组合搜索

---

## 5. 范围边界

### MVP 包含（v1.0）
- `mdnotes search <query>` 命令
- FTS5 全文索引（title + content + tag）
- unicode61 tokenizer（中文支持）
- trigger 自动同步（INSERT / UPDATE / DELETE）
- 边界 case 全覆盖（见 §6 关键约束）
- exit code 类 grep（0/1/2）
- `--tag <name>` 筛选
- `--color=auto|always|never`
- `--limit N`（默认 100）

### v2 后续（不在本 PRD 范围）
- 模糊匹配（fuzzy search）
- 多词 AND/OR 组合语法
- BM25 rank 排序自定义
- highlight 排序展示
- 组合搜索（`search "x" --tag "y"` 联合筛选）
- 日期过滤（`search "x" --since 2024-01-01`）
- `--refresh` 手动刷新 FTS5 索引

### 明确不做
- LIKE fallback（FTS5 是 v1.0 锁定技术选型）
- 非 Python 3.14 / SQLite 3.46.1 环境支持
- 云端同步搜索
- 文件名搜索（搜索笔记内容，不是 .md 文件名）

---

## 6. 验收标准（业务层面）

### 功能验收
- [ ] `mdnotes search "keyword"` 返回 title/content/tag 包含 keyword 的所有笔记
- [ ] `mdnotes search --tag "python"` 只返回 tag_name='python' 的笔记
- [ ] 无结果时 exit code 1，友好提示"未找到匹配笔记"
- [ ] FTS5 语法错误时 exit code 2，提示具体错误
- [ ] `mdnotes search`（无 query）时 exit code 2，提示"用法：mdnotes search <query>"

### 交互验收
- [ ] `mdnotes search "hello world"`（无引号）= OR 语义
- [ ] `mdnotes search "\"hello world\""`（有引号）= AND 语义
- [ ] 特殊字符 `' " & |` CLI 预处理或友好报错
- [ ] `--color=auto` 时 terminal 直出高亮，pipe less 时提示 `less -R`
- [ ] 结果超过 100 条时截断，输出"显示前 100 条，共 N 条"

### 同步验收
- [ ] `mdnotes add` 后立即 search 能搜到新笔记（trigger 同步）
- [ ] `mdnotes delete` 后立即 search 搜不到已删除笔记
- [ ] `mdnotes tag rename v1 v2` 后，`search --tag v2` 立即搜到，`search --tag v1` 搜不到
- [ ] rename 影响超过 10 条时输出 warning

### 性能验收
- [ ] 1000 笔记 P95 冷缓存响应时间 ≤ 100ms
- [ ] 中文查询 `"性能优化"` 正常工作（unicode61 tokenize）

### 维护验收
- [ ] `mdnotes search --check` 返回索引健康状态（rowid 对照方案）
- [ ] `mdnotes search --rebuild` 在线 rebuild（无 downtime），幂等可重复执行
- [ ] FTS5 不可用时报错 "FTS5 not available"，不静默 fail

### 边界 case 验收
- [ ] empty query → exit code 2
- [ ] special chars（' " & |）→ 预处理或报错
- [ ] Chinese characters（连续词 + 单字）→ 正常工作
- [ ] large result set（> 100 条）→ 截断 + 提示共 N 条
- [ ] no result → exit code 1 + 友好提示
- [ ] multi-file results → 每行显示文件路径
- [ ] file path with spaces → 加引号 `"my notes/test.md"`
- [ ] vault with no .md files → exit code 1 + "未找到匹配笔记"

---

## 7. 关键约束（辩论共识）

以下 5 项约束来自 3 轮辩论（product-champion / tech-reviewer / devil-advocate / quality-gatekeeper）收敛共识：

### 约束 1：FTS5 技术锁定
- **必须使用** FTS5 virtual table（否决 LIKE MVP 方案）
- Schema：`content='notes'` 关联型，UUID + rowid 双 ID
- Tokenizer：`unicode61`（中文支持唯一选项）
- 不提供 LIKE fallback（v1.0 锁定）

### 约束 2：trigger 自动同步
- 3 个 trigger（INSERT / UPDATE / DELETE）
- UPDATE trigger = DELETE + INSERT（FTS5 content= 关联模式）
- 单行 update 场景：事务内 trigger 同步（可接受）
- 批量 update 场景（> 10 条）：warning 提示 FTS5 可能不一致
- FTS5 不可用时：CLI 启动报错，CI fail-fast

### 约束 3：CLI query 预处理
- 无引号：FTS5 OR 语义（`python redis` = python OR redis）
- 有引号：FTS5 AND 语义（`"python redis"` = python AND redis）
- 文档明确说明引号语义（类 Google 搜索）
- 特殊字符（& | - " *）：CLI 预处理转义

### 约束 4：性能门禁
- P95 冷缓存 ≤ 100ms（1000 笔记）
- 集成测试必须包含至少 1000 条笔记性能测试
- rebuild 期间搜索服务不中断（在线 rebuild）

### 约束 5：测试覆盖
- 单元测试：mock FTS5，验证 CLI 参数、query 预处理、exit code
- 集成测试：真 FTS5 + 1000 条笔记
- 边界 case 8 个必跑（见 §6）
- FTS5 不可用时 CI fail（不允许 skip）

---

## 8. 风险提示

### 风险 1：FTS5 模块依赖（已仲裁）
- **描述：** FTS5 不是所有 Python 发行版都可用（精简版 SQLite / 移动端 Python）
- **概率：** 中（桌面 Python 大概率有，容器/虚拟环境不确定）
- **缓解：** README 声明依赖 Python 3.14 + SQLite 3.46.1+；m920x 已验证可用；CI 要求 FTS5 环境
- **升级条件：** FTS5 不可用时 CLI 报错，不静默降级

### 风险 2：中文支持边界（已验证）
- **描述：** FTS5 unicode61 tokenizer 对某些 CJK 字符序列分词可能不符合用户预期
- **概率：** 低（中文字符串匹配在 unicode61 下通常是准确的）
- **缓解：** 集成测试必须包含中文连续词 + 单字匹配 case；文档说明 unicode61 分词行为

### 风险 3：statement-level trigger 批量 update（已仲裁）
- **描述：** SQLite trigger 是 statement-level，批量 UPDATE 时只同步最后一条记录
- **概率：** 低（单行 rename 是主要场景）
- **缓解：** rename 影响 > 10 条时 warning；auto-check 发现不一致时提示 rebuild
- **升级条件：** v2 考虑 row-level trigger 模拟

### 风险 4：FTS5 MATCH 语法与用户直觉不符（已缓解）
- **描述：** 用户输入 `"hello world"` 期望 AND，但 FTS5 默认 OR
- **概率：** 高（CLI 新用户不熟悉 FTS5 语法）
- **缓解：** CLI query 预处理（无引号 = OR，有引号 = AND）；文档明确说明
- **监控：** 用户反馈"搜不到"时优先检查引号语义

### 风险 5：tag rename 后 FTS5 索引不一致（已缓解）
- **描述：** 批量 rename 时 statement-level trigger 导致 FTS5 索引不完整
- **概率：** 低（rename 通常影响少量笔记）
- **缓解：** > 10 条时 warning；auto-check；--rebuild 在线修复
- **升级条件：** rename 后立即 search --check 发现不一致时提示 rebuild

---

## 附录：技术决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 搜索技术 | FTS5（否决 LIKE）| content 搜索 LIKE 无索引，性能差距 5-30x |
| FTS5 schema | content='notes' 关联型 | 与 notes 表保持同步，避免数据冗余 |
| Tokenizer | unicode61 | 中文支持唯一选项 |
| Trigger 模式 | statement-level | SQLite 原生，事务边界内行为正确 |
| Rebuild 策略 | 在线（ALTER RENAME）| 无 downtime，原子切换 |
| Check SQL | rowid 对照方案 | 比 count 对照更准确，SQLite 通用 |
| Exit code | 类 grep（0/1/2）| 脚本调用者熟悉，易集成 |
| CLI 引号语义 | 无引号=OR，有引号=AND | 类 Google 搜索直觉，文档明确说明 |

---

*PM 辩论收敛完成。SPEC 由 Architect 依据本 PRD 自主撰写。*
