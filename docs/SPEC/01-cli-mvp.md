# mdnotes CLI MVP — 技术规范

> **Task ID:** t_20260618_be84ae
> **作者:** Architect Agent
> **依据:** `docs/PRD/01-cli-mvp.md`（PM Agent 输出）+ 3 轮辩论收敛记录
> **创建时间:** 2026-06-18T19:30:00+08:00

---

## 接口设计

### CLI 命令（≥ 3 个端点）

#### `mdnotes add <title> [content]`
- **位置参数**: `title`（必填，字符串，最大 200 字符）、`content`（可选）
- **exit code**: 0 成功（返回 note_id）/ 1 系统错误 / 2 参数错误
- **输出**: 成功后输出 `Created note <id>`（stderr），`<id>` 为整数
- **行为**: 首次执行时自动创建 `~/.mdnotes/` 目录和 `notes.db` SQLite 数据库

#### `mdnotes list [--search <keyword>] [--sort created_at|updated_at] [--order asc|desc]`
- **选项**: `--search` 标题 LIKE 模糊匹配 / `--sort` 排序字段 / `--order` 升序或降序
- **exit code**: 0 始终（即使无笔记）
- **输出格式**: `[<id>] <title> (<created_at>)`，每行一条，按 `created_at DESC` 默认排序
- **空状态**: 输出 `No notes yet.` + exit 0

#### `mdnotes show <id>`
- **位置参数**: `id`（必填，整数）
- **exit code**: 0 成功 / 2 参数错误（非整数）/ 3 笔记不存在
- **输出格式**: 三个区块
  ```
  Title: <title>
  Created: <created_at>
  ----
  <渲染后的 Markdown content>
  ```
- **Markdown 渲染**: 标题/列表/链接/代码块，特殊字符（`*_`）不引发注入

#### `mdnotes delete <id> [--force]`
- **位置参数**: `id`（必填，整数）
- **选项**: `--force` 跳过确认提示
- **exit code**: 0 成功 / 2 参数错误 / 3 笔记不存在（幂等）
- **输出**: 成功后 stderr 输出 `Deleted note <id>`
- **行为**: 删除后物理移除（PRAGMA vacuum），该 id 不可再被 show 查询

---

## 数据结构

### SQLite 表结构

```sql
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    content    TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
```

### CLI 输出数据结构

**list 输出行**:
```
[<id>] <title> (<created_at>)
```
- `id`: 十进制整数，无前导零
- `title`: 原始字符串，不转义
- `created_at`: ISO 8601 本地时间 `YYYY-MM-DD HH:MM:SS`

**show 输出区块**:
```
Title: <title>
Created: <created_at>
----
<rendered markdown content>
```

**错误输出（stderr）**:
- 参数错误: `Error: <具体原因>`
- 资源不存在: `Note not found`
- 系统错误: `Error: <系统错误描述>`

### exit code 规范

| 退出码 | 含义 | 触发条件 |
|--------|------|---------|
| 0 | 成功 | add/list/show/delete 正常执行 |
| 1 | 系统错误 | 磁盘满/权限错误/database corruption |
| 2 | 参数错误 | 空标题/超长标题/非整数 id/未知选项 |
| 3 | 资源不存在 | show/delete 不存在的 id（幂等） |

---

## 验收标准（技术层面）

- [ ] **AC-1**: 标题非空（去首尾空格后长度 > 0）→ exit 2
- [ ] **AC-2**: 标题最大 200 字符，超长拒绝 → exit 2
- [ ] **AC-3**: 内容允许空字符串 → exit 0
- [ ] **AC-4**: add 成功后返回 note_id（整数）
- [ ] **AC-5**: add 后数据可被 list 列出
- [ ] **AC-6**: SQLite 写入失败 → exit 1 并在 stderr 输出错误
- [ ] **AC-7**: 重复标题不报错（无唯一性约束）
- [ ] **AC-8**: list 输出每行 `[id] title (created_at)` 格式稳定
- [ ] **AC-9**: list 默认 `created_at DESC` 排序（最新在前）
- [ ] **AC-10**: `--sort created_at|updated_at --order asc|desc` 正确解析
- [ ] **AC-11**: 无笔记时 `No notes yet.` + exit 0
- [ ] **AC-12**: list 不暴露 content（性能 + 隐私）
- [ ] **AC-13**: show 输出 title/created_at/content 三区块
- [ ] **AC-14**: content Markdown 正确渲染（标题/列表/链接/代码块）
- [ ] **AC-15**: Markdown 特殊字符（`*_`）不引发注入或格式破坏
- [ ] **AC-16**: 不存在的 id → exit 3 + stderr "Note not found"
- [ ] **AC-17**: 非整数 id → exit 2 + 提示参数类型错误
- [ ] **AC-18**: 删除已存在的 id → exit 0 + stderr "Deleted note N"
- [ ] **AC-19**: 删除不存在的 id → exit 3 + stderr "Note not found"（幂等）
- [ ] **AC-20**: `--force` 跳过确认提示
- [ ] **AC-21**: 删除后该 id 不可被 show 查询到
- [ ] **AC-22**: 每个命令 `--help` 输出有效帮助文档
- [ ] **AC-23**: DB 路径固定 `~/.mdnotes/notes.db` + `MDNOTES_DB` 环境变量覆盖
- [ ] **AC-24**: 含空格路径支持

---

## 边界情况

| 边界情况 | 处理方式 |
|---------|---------|
| 空标题（`""`） | 去首尾空格后长度为 0 → exit 2 |
| 纯空格标题 | 去首尾空格后长度为 0 → exit 2 |
| 超长标题（> 200 字符） | 拒绝写入 → exit 2 |
| 空内容（`""`） | 允许 → exit 0 |
| 控制字符（`\x00`） | 清洗或拒绝 → exit 2（可接受行为） |
| 非整数 id（`show abc`） | → exit 2 + "id must be an integer" |
| 不存在的 id | → exit 3 + stderr "Note not found" |
| SQLite 写入失败（磁盘满） | → exit 1 + stderr "Database error: ..." |
| SQLite 数据库文件被锁定 | 重试 3 次（100ms / 200ms / 400ms 指数退避）→ 仍失败 exit 1 |
| 含空格路径（`/path/with spaces/notes.db`） | 必须支持（Python sqlite3 原生支持） |
| ASCII 特殊字符路径 | 必须支持 |
| 非 ASCII 路径（中文/日文目录名） | **known limitation**：不主动测试 |
| Windows 反斜杠路径 | **known limitation**：不主动测试 |
| SQLite 数据库 corruption | 检测到 corruption → exit 1 + "Database corrupted" |

---

## 依赖

### Python 版本
- **Python >= 3.10**（内置 sqlite3 需要 3.10+，其他依赖无版本冲突）

### 新增依赖（pip 包）

| 包 | 版本 | 用途 |
|----|------|------|
| `click` | >= 8.0 | CLI 参数解析框架 |
| `mistune` | >= 3.0 | Markdown 渲染（选型见 ADR-0001） |

> **注意**：不使用 SQLAlchemy，使用 Python 内置 `sqlite3`

### 内部模块（源码结构）

```
src/mdnotes/
├── __init__.py          # 包入口
├── cli.py               # Click 命令组 + add/list/show/delete 实现
├── storage.py           # SQLite 操作（CRUD + integrity check）
└── render.py            # Markdown 渲染（mistune）
```

---

## 实施指南

### 步骤 1：初始化项目结构
1. 创建 `src/mdnotes/{__init__.py, cli.py, storage.py, render.py}`
2. `click` 作为入口框架，`cli.py` 定义 4 个命令
3. `storage.py` 管理 SQLite 连接、CRUD、重试逻辑
4. `render.py` 封装 mistune 渲染

### 步骤 2：DB 初始化
1. `storage.py` 在首次 `add` 时检查 `~/.mdnotes/` 目录是否存在，不存在则创建
2. 创建 `notes.db` 并执行 `CREATE TABLE IF NOT EXISTS notes (...)`
3. 使用 `datetime('now', 'localtime')` 确保时区正确

### 步骤 3：实现 CLI 命令
1. `add`: 验证标题 → `storage.add_note()` → 输出 note_id
2. `list`: 解析 `--search/--sort/--order` → `storage.list_notes()` → 格式化输出
3. `show`: 解析 id → `storage.get_note()` → `render.markdown()` → 输出
4. `delete`: 解析 id → 确认提示（无 `--force`）→ `storage.delete_note()` → vacuum

### 步骤 4：测试策略（分层）

| 测试层 | 工具 | 场景 |
|--------|------|------|
| 单元测试 | `pytest` + `unittest` | `render.py` markdown 渲染 / `storage.py` SQL 逻辑 |
| 集成测试 | `click.testing.CliRunner` + `:memory:` SQLite | 全部 4 个命令的参数解析、exit code、输出格式 |
| E2E 测试 | `subprocess` + `tmpdir` | 全链路 add→list→show→delete，路径含空格 |
| 并发测试（P2 监控） | `multiprocessing` + `tmpdir` | 10 进程并发 add，检测 deadlock |

### 步骤 5：integrity check 方案（规避 data corruption 风险）
1. `storage.py` 每次写入后执行 `PRAGMA integrity_check`
2. 如 integrity_check 返回非空错误，执行 `PRAGMA quick_check` 二次确认
3. corruption 检测到 → exit 1 + 提示用户 `mdnotes init --rebuild`
4. delete 后执行 `VACUUM` 立即回收磁盘空间（规避 AC-26）

---

## 源码文件清单

| 文件 | 职责 |
|------|------|
| `src/mdnotes/__init__.py` | 包版本 `__version__ = "0.1.0-mvp"` |
| `src/mdnotes/cli.py` | Click 命令组；`add/list/show/delete` 命令；`--help` |
| `src/mdnotes/storage.py` | `add_note/get_note/list_notes/delete_note`；SQLite 重试逻辑；`init_db` |
| `src/mdnotes/render.py` | `render_md(content: str) -> str`；mistune 封装 |
| `tests/` | 39 个测试（26 核心 + 13 可补充） |
| `pyproject.toml` | 项目元数据 + 依赖声明 + `scripts.mdnotes` console_scripts 入口 |
