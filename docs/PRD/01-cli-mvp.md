# mdnotes CLI MVP — 产品需求文档

> **Task ID:** t_20260618_be84ae
> **作者:** PM Agent（3 轮辩论收敛产出）
> **创建时间:** 2026-06-18T19:16:04+08:00
> **版本:** v1.0（辩论收敛版）

---

## 用户故事

- **作为技术写作者**，我想要一个**轻量、无依赖、本地可用的 Markdown 笔记 CLI 工具**，以便我在终端中**快速记录、检索和管理技术笔记**，而不需要打开 GUI 应用或注册账户。
- **作为开发者**，我想要一个**可脚本化的笔记工具**，以便我**用管道命令（pipe）将笔记内容与其他工具（grep、jq）结合**，实现自动化工作流。
- **作为个人知识管理爱好者**，我想要**结构化的笔记存储**（SQLite），以便我**用 SQL 查询我的笔记库**，而不是用文件系统管理一堆散乱的 .md 文件。

---

## 业务流程

1. **首次使用**：用户运行 `mdnotes add <title> [content]`，CLI 自动创建 `~/.mdnotes/notes.db`（或 `MDNOTES_DB` 环境变量指定路径），初始化 SQLite 表结构
2. **添加笔记**：用户输入标题（必填）+ 内容（可选），CLI 写入 SQLite，返回 note_id
3. **列出笔记**：用户运行 `mdnotes list`，看到所有笔记的 id + title（按创建时间倒序）
4. **搜索笔记**：用户运行 `mdnotes list --search <keyword>`，看到标题含关键词的笔记（LIKE 模糊匹配）
5. **查看笔记**：用户运行 `mdnotes show <id>`，看到单条笔记的完整内容（含 Markdown 渲染）
6. **删除笔记**：用户运行 `mdnotes delete <id>`（确认提示）或 `mdnotes delete --force <id>`（跳过确认），笔记从数据库移除

---

## 业务价值 / ROI

- **解决的问题：** Notion/飞书文档等工具太重（需要账户、GUI、网络）；纯文本文件无结构化管理（文件名冲突、无法 SQL 查询、无法结构化检索）
- **预期收益：** 用户写笔记速度比 Notion 快 3 倍（无 GUI、无加载时间），且笔记可被 SQL 查询和脚本化
- **优先级：** P0 — 主公 2026-06-18 决策启动

---

## 目标用户精细化定义

**核心用户画像：技术写作者（Technical Writer）**

| 维度 | 描述 |
|------|------|
| 技能特征 | 熟悉命令行操作，习惯用文本编辑器（Vim/Emacs/VS Code）编写 Markdown |
| 工作场景 | 编写技术文档、API 文档、开发日志、会议记录、代码注释 |
| 痛点 | 已有笔记工具（Notion/Obsidian）太重，需要 GUI 才能使用；纯文本文件无法结构化管理 |
| 期望 | 轻量、快速、可脚本化的本地笔记工具，不需要网络同步，不需要账户注册 |
| 典型数量 | 个人使用，笔记量 10~500 条 |

**不在目标用户范围内：**
- 需要多设备同步的用户（Notion/飞书文档更适合）
- 需要富文本编辑器的用户（Obsidian/TiddlyWiki 的 GUI 更适合）
- 团队协作场景（Notion/Confluence 更适合）
- Windows Server 管理员（Unicode/UNC 路径作为 known limitation）

### 与竞品的差异化陈述

| 竞品 | mdnotes 的差异化 |
|------|----------------|
| **Obsidian** | Obsidian 是 GUI 驱动的本地知识库（Electron 应用），强调双向链接和图谱视图。mdnotes 是纯 CLI，零 GUI，适合终端用户和脚本自动化场景。 |
| **TiddlyWiki** | TiddlyWiki 是单 HTML 文件的非线性笔记工具，强调可移植性。mdnotes 强调 SQLite 结构化存储 + Markdown 渲染，适合需要可查询笔记库的场景。 |
| **Notion** | Notion 是云端协作平台，需要账户和网络。mdnotes 是完全本地、无账户、离线可用的工具。 |
| **grep + cat 手动管理文本文件** | mdnotes 提供结构化存储（id/created_at/updated_at）、SQLite 查询能力、一致性 exit code，笔记不会因为文件名冲突或路径混乱而丢失。 |

**核心差异化标语**："Obsidian 太重，grep 太轻——mdnotes 在两者之间提供结构化本地笔记"

---

## 范围边界

### 包含（MVP 明确包含）

| 功能 | 说明 |
|------|------|
| `mdnotes add <title> [content]` | 创建笔记，标题必填，内容可选 |
| `mdnotes list` | 列出所有笔记（id + title，created_at DESC） |
| `mdnotes list --search <keyword>` | 标题 LIKE 模糊匹配搜索（SQLite 原生支持，零新依赖） |
| `mdnotes list --sort created_at|updated_at --order asc|desc` | 排序选项 |
| `mdnotes show <id>` | 显示单条笔记（含 Markdown 渲染） |
| `mdnotes delete <id>` | 删除笔记（带确认提示） |
| `mdnotes delete --force <id>` | 删除笔记（跳过确认，用于自动化脚本） |
| `mdnotes add/list/show/delete --help` | 每个命令的有效帮助文档 |
| SQLite 本地存储 | 默认 `~/.mdnotes/notes.db`，`MDNOTES_DB` 环境变量覆盖 |
| 路径处理 | 空格 + ASCII 特殊字符路径必须支持 |
| 39 个测试 | 26 个核心 + 13 个可补充测试 |
| 10 项 DoD | MVP 发布门槛 |

### 不包含（明确排除，进入 v1.0 backlog）

| 功能 | 排除理由 |
|------|---------|
| content 全文搜索（FTS） | MVP 验证"结构化检索"假设，标题搜索已足够 |
| 笔记编辑（edit/update） | MVP 只验证"持久化 + 检索"，增删查是最小集 |
| 标签/分类/文件夹 | 增加认知成本，MVP 不验证多维度组织假设 |
| 多笔记并发编辑（实时协作） | 完全本地工具，无协作场景 |
| 云同步/多设备同步 | 与"轻量本地工具"定位矛盾 |
| SQLAlchemy ORM | 使用 Python 内置 sqlite3（Round 1 收敛） |
| 非 ASCII 路径（中文/日文目录名） | 作为 known limitation 记录，不主动测试 |
| Windows 反斜杠路径深度处理 | 作为 known limitation 记录 |
| Markdown 编辑器（编辑时渲染预览） | show 命令已提供渲染输出 |
| 笔记导入/导出（JSON/Markdown 文件批量导入） | v1.0 backlog |
| 搜索历史/模糊匹配/正则搜索 | 标题 LIKE 是 MVP 上限 |
| 二次确认撤销（undo） | delete 是最终删除，无撤销 |
| 标题唯一性约束 | 允许重复标题（v1.0 考虑） |
| VACUUM/自动磁盘回收 | 属于性能优化轮次 |

---

## 验收标准（业务层面）

### 🔴 MVP 必须通过（26 个核心测试）

#### add 操作
- [ ] **AC-1**：标题非空字符串，去首尾空格后长度 > 0；空标题 → exit 2
- [ ] **AC-2**：标题最大长度 ≤ 200 字符，超长拒绝 → exit 2
- [ ] **AC-3**：内容可以为任意字符串（包括空字符串 ""）→ exit 0
- [ ] **AC-4**：成功后返回 note_id（整数），且可被后续 show/delete 使用
- [ ] **AC-5**：add 后数据可被 list 列出
- [ ] **AC-6**：SQLite 写入失败（如磁盘满、权限错误）→ exit 1 并提示
- [ ] **AC-7**：重复标题不报错（无唯一性约束）

#### list 操作
- [ ] **AC-8**：输出每行包含 id 和 title，格式稳定（`[id] title (created_at)`）
- [ ] **AC-9**：默认按 created_at DESC 排序（最新在前）
- [ ] **AC-10**：`--sort created_at|updated_at --order asc|desc` 参数解析正确
- [ ] **AC-11**：无笔记时输出 "No notes yet."，exit 0
- [ ] **AC-12**：list 输出不暴露 content（性能 + 隐私）

#### show 操作
- [ ] **AC-13**：输出包含 title、created_at、content 三个区块
- [ ] **AC-14**：content 中的 Markdown 正确渲染（标题/列表/链接/代码块）
- [ ] **AC-15**：Markdown 特殊字符（`*_` 等）不引发注入或格式破坏
- [ ] **AC-16**：不存在的 id → exit 3，stderr "Note not found"
- [ ] **AC-17**：非整数 id → exit 2，提示参数类型错误

#### delete 操作
- [ ] **AC-18**：删除已存在的 id → exit 0，stderr 确认 "Deleted note N"
- [ ] **AC-19**：删除不存在的 id → exit 3，stderr "Note not found"（幂等性）
- [ ] **AC-20**：`--force` 跳过确认提示
- [ ] **AC-21**：删除完成后该 id 不可被 show 查询到

#### 全局
- [ ] **AC-22**：每个命令 `--help` 输出有效帮助文档
- [ ] **AC-23**：DB 路径固定为 `~/.mdnotes/notes.db`，不可用户自定义
- [ ] **AC-24**：Windows 含空格路径支持

### 🟡 可接受（不实现需文档说明）

- [ ] **AC-25**：标题/内容中的控制字符（如 `\x00`）需清洗或拒绝
- [ ] **AC-26**：删除后 SQLite 磁盘占用应回收（或至少文件不增大）
- [ ] **AC-27**：非 ASCII 路径（中文/日文目录名）—— 记录为 known limitation

### 🟢 建议补充（v0.x 迭代）

- [ ] Markdown golden file 精细测试（代码块/链接/嵌套列表）
- [ ] `--sort updated_at` 排序验证
- [ ] `--order asc` 升序验证
- [ ] list 输出 COLUMNS 可变宽度不截断
- [ ] 极长 Markdown 内容（>10KB）处理
- [ ] 磁盘满场景模拟

### ⚫ v1.0 backlog

- [ ] content 全文搜索（FTS）
- [ ] 笔记编辑（edit/update）
- [ ] 标签/分类
- [ ] 标题唯一性约束
- [ ] 二次确认撤销

---

## 关键约束（辩论共识）

### 产品约束
- **MVP 核心假设**：技术写作者需要轻量本地笔记工具（而非 Notion/Obsidian 等 GUI 工具）
- **差异化**：纯 CLI + SQLite 结构化存储，零 GUI，零账户，零网络依赖
- **成功指标**：E2E 全链路通过率 100%；Critical = 0；MVP 发布后 30 天至少 5 个目标用户反馈

### 技术约束
- **Python >= 3.10**，Click >= 8.0，使用内置 `sqlite3`（不使用 SQLAlchemy）
- **Markdown 渲染库**：`markdown-it-py` 或 `mistune`（Architect 在 ADR 中记录选型）
- **DB 路径**：默认 `~/.mdnotes/notes.db`（Linux/macOS），通过 `MDNOTES_DB` 环境变量覆盖
- **首次 add 自动初始化**：创建 `~/.mdnotes/` 目录 + 初始化 SQLite 表
- **路径处理**：空格 + ASCII 特殊字符路径必须支持；非 ASCII（Unicode）路径为 known limitation
- **exit code 规范**：0=成功，1=系统错误（磁盘满/权限），2=参数错误，3=资源不存在（not found）
- **并发安全**：SQLite `database is locked` 最多重试 3 次（100ms / 200ms / 400ms 指数退避）
- **SQLite 配置**：默认 rollback journal，WAL 模式按需评估（并发冲突率 > 1% 时 ADR 决策）

### 质量约束
- **26 个 MVP 核心测试 100% 通过**，Critical = 0，Major ≤ 2
- **DoD 10 项**（9 项 MVP 门槛 + 1 项 P2 监控）：39 测试 100% 通过 / Critical=0 / help 文档 / exit 2-3 错误码 / Markdown 基础渲染 / E2E 全链路 / 无开发残留 + 并发监控
- **P0 回滚线**：SQLite 写入后 data corruption / delete 后数据仍可 show / 静默失败（exit 0 但未执行）—— 任一发生立即回滚
- **测试分层**：`db_memory`（`:memory:` 快速测试）+ `db_tmpfile`（路径/并发真实场景）

---

## 风险提示

### Devil's Advocate 提出的已知风险（已接受为 known limitation）

| 风险 | 严重程度 | 处理方式 |
|------|---------|---------|
| 无 content 全文搜索，20+ 条笔记后实用性受限 | 中 | MVP 加 `list --search`（标题 LIKE 搜索）缓解；content 搜索入 v1.0 |
| 非 ASCII 路径（中文/日文目录名）在 Windows 上可能失败 | 低 | 记录为 known limitation；Python 3.10+ 默认 UTF-8 支持 |
| Windows SQLite `database is locked` 比 Linux 更频繁 | 低 | 重试 3 次 + 指数退避；并发冲突率 > 1% 则评估 WAL |
| 笔记工具无 GUI，学习成本比纯文件管理器高 | 低 | 目标用户是熟悉命令行的技术写作者，不是普通用户 |
| MVP 无获客策略，种子用户从何而来 | 低 | 主公通过 GitHub 发布 + README 说明适用场景 |

### 架构风险（Architect 需在 SPEC 中给出技术方案）

| 风险 | 处理要求 |
|------|---------|
| SQLite 写入后 data corruption | Architect 必须在 SPEC 中明确 integrity check 方案 |
| delete 后数据仍可被 show（数据泄露） | AC-21 覆盖，Architect 确保物理删除 + vacuum |
| 静默失败（exit 0 但操作未执行） | AC-6 覆盖，Architect 确保所有失败路径有 exit 1 |

---

## 成功指标（辩论共识）

| 假设 | 验证指标 | 验收阈值 |
|------|---------|---------|
| H1: 用户能成功添加笔记并检索 | E2E 全链路测试 add→list→show→delete 通过率 | 100% |
| H2: 笔记数据不丢失/不损坏 | 26 个核心测试 0 failure | Critical = 0 |
| H3: 目标用户接受 CLI 交互方式 | MVP 发布后 30 天内至少 5 个目标用户反馈 | 至少 3/5 认为"可用" |
| H4: SQLite 是合适的存储后端 | `db_memory` + `db_tmpfile` 分层测试覆盖全部 happy path + 错误路径 | 测试覆盖率 ≥ 85% |
| H5: 标题搜索提升可用性 | `list --search` 能正确返回匹配标题的笔记 | LIKE 查询返回结果正确 |

---

## 辩论收敛记录

### 议题收敛状态（3 轮辩论后全部收敛）

| 议题 | 收敛状态 | 最终决定 |
|------|---------|---------|
| MVP 范围（add/list/show/delete） | ✅ 收敛 | 确认 |
| `list --search` LIKE 搜索 | ✅ 收敛 | 加入 MVP（Round 3 PC 接受 Devil 建议） |
| 无 SQLAlchemy | ✅ 收敛 | 使用内置 sqlite3 |
| DB 路径策略 | ✅ 收敛 | `~/.mdnotes/notes.db` + `MDNOTES_DB` 覆盖 |
| 路径处理分层 | ✅ 收敛 | 空格/ASCII 必须；Unicode known limitation |
| 测试数量 | ✅ 收敛 | 26 核心 + 13 可补充（39 总设计） |
| DoD-8 并发测试 | ✅ 收敛 | 从 MVP 门槛降为 P2 监控指标 |
| Markdown 渲染库选型 | ✅ 收敛 | Architect 在 ADR 中记录 |
| SQLite journal mode | ✅ 收敛 | 默认 rollback journal；WAL 按需评估 |

### 辩论关键转变点

1. **Round 1**：Devil's Advocate 提出"无搜索对笔记工具是致命的"，Product Champion 以"Unix 哲学"反驳
2. **Round 2**：Tech Reviewer 提出 SQLite LIKE 搜索成本极低（~10 行）；Quality Gatekeeper 揭示并发测试与 `:memory:` 的矛盾
3. **Round 3**：Product Champion 接受 LIKE 搜索加入 MVP（技术成本低 + Devil 的用户体验批评有效）；Devil's Advocate 接受 MVP（含搜索）并声明收敛；Quality Gatekeeper 确认 26 核心测试 + 13 可补充的最终测试数量

### 未收敛升级 PM 仲裁（无）

本次辩论所有议题在 3 轮内收敛，无需 PM 仲裁。

---

## 附录

### DB Schema

```sql
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    content    TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

### exit code 规范

| 退出码 | 含义 |
|--------|------|
| 0 | 操作成功 |
| 1 | 系统错误（磁盘满/权限/数据库损坏） |
| 2 | 参数错误（空标题/超长标题/非法 id 格式） |
| 3 | 资源不存在（笔记 id 不存在） |

### 命令行接口

```
mdnotes add <title> [content]         # 创建笔记
mdnotes list [--sort created_at|updated_at] [--order asc|desc] [--search <keyword>]
mdnotes show <id>                     # 显示笔记（含 Markdown 渲染）
mdnotes delete <id>                   # 删除（确认提示）
mdnotes delete --force <id>           # 强制删除（无确认）
```
