# ADR-0003 — SQLite 数据库路径策略

> **日期**：2026-06-18
> **状态**：Accepted
> **适用版本**：v1.5.0+
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/01-cli-mvp.md` / `docs/SPEC/01-cli-mvp.md`

## 背景

mdnotes 是纯本地 CLI 工具，需要决定：
1. 数据库文件放在哪个路径？
2. 首次运行时如何初始化（谁来创建目录和表）？
3. 用户能否自定义路径？

PRD 辩论（Round 2）揭示：Tech Reviewer 提出"DB 路径策略缺失"是架构前置问题，需要明确。

## 决策

**固定路径 + 环境变量覆盖**：
- **默认路径**：`~/.mdnotes/notes.db`（`$HOME` 由 Python `os.path.expanduser()` 展开）
- **自定义路径**：`MDNOTES_DB` 环境变量覆盖默认路径（支持绝对路径或相对路径）
- **初始化时机**：首次 `add` 时自动创建 `~/.mdnotes/` 目录 + `notes.db` 表结构

## 考虑的替代方案

### 方案 A：`~/.mdnotes/notes.db` + `MDNOTES_DB` 覆盖（采纳）

- ✅ 路径固定，用户无需记忆（工具自动管理）
- ✅ `MDNOTES_DB` 支持自定义路径（多数据库场景，如工作/个人分开）
- ✅ 首次 add 自动初始化，零手动配置
- ✅ 符合 XDG Base Directory Specification 精神（工具数据放 `~/.config/` 或 `~/.local/` 下）
- ❌ 路径硬编码在代码中（但 `~` 展开是标准做法）

### 方案 B：用户手动 `mdnotes init` 初始化

- ✅ 用户显式控制数据库路径
- ✅ 初始化失败可以提早发现
- ❌ 增加一个必须记住的命令（违背"轻量"承诺）
- ❌ 用户可能忘记运行 init 导致首次 add 报错

### 方案 C：当前目录 `notes.db`（无固定位置）

- ✅ 笔记数据和笔记项目放在一起，适合版本控制场景
- ❌ 每次运行需要 `cd` 到正确目录
- ❌ 无法用绝对路径引用，脚本化困难
- ❌ 多项目用户可能混淆不同目录的数据库

### 方案 D：`$XDG_DATA_HOME/mdnotes/notes.db`（XDG 标准）

- ✅ 符合 XDG 规范（`~/.local/share/mdnotes/notes.db`）
- ❌ 路径较深，用户不易手动查看
- ❌ 需要判断 `$XDG_DATA_HOME` 是否存在（Windows/macOS 兼容性问题）

## 决定

**采纳方案 A：`~/.mdnotes/notes.db` + `MDNOTES_DB` 覆盖**。

理由：固定 `~/.mdnotes/` 路径符合工具定位（本地笔记工具，用户主目录下），自动初始化减少摩擦，`MDNOTES_DB` 覆盖提供必要的灵活性。`~/.mdnotes/` 比 `~/.local/share/mdnotes/` 更短、更直观，比 XDG 方案兼容性更好（直接用 `os.path.expanduser("~")`）。

## 后果

### 正面

- ✅ 用户无需任何配置，开箱即用
- ✅ `MDNOTES_DB=/path/to/custom.db mdnotes list` 支持多数据库场景
- ✅ `~/.mdnotes/` 目录对用户隐藏，符合"工具管理数据"心智模型
- ✅ 绝对路径下的 `notes.db` 可被 `sqlite3 ~/.mdnotes/notes.db` 直接查询

### 负面

- ❌ `~` 在某些边缘场景（root 用户 `/root` vs `$HOME` 指向非标准路径）可能非预期
  - **缓解**：Python `os.path.expanduser("~")` 由 OS 提供，行为一致
- ❌ 无法指定数据库文件名（固定 `notes.db`）
  - **影响**：多数据库场景只能用不同目录，无法同目录不同文件名
  - **升级**：v1.0 backlog 中评估 `MDNOTES_DB` 支持目录路径（自动在该目录下创建 `notes.db`）

### 实现约束

```python
import os
DB_DIR = os.path.expanduser("~/.mdnotes")
DB_PATH = os.environ.get("MDNOTES_DB", os.path.join(DB_DIR, "notes.db"))
```

初始化逻辑（`storage.py`）：
```python
def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(CREATE_TABLE_SQL)  # CREATE TABLE IF NOT EXISTS
    return conn
```
