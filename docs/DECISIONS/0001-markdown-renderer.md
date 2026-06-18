# ADR-0001 — Markdown 渲染库选型

> **日期**：2026-06-18
> **状态**：Accepted
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/01-cli-mvp.md` / `docs/SPEC/01-cli-mvp.md`

## 背景

mdnotes CLI MVP 的 `show` 命令需要将笔记的 Markdown 内容渲染为纯文本终端输出（支持标题/列表/链接/代码块）。同时 PRD 明确排除"手写正则解析 Markdown"，必须使用成熟的开源渲染库。

技术约束（PRD 辩论共识）：
- Python >= 3.10
- 零新增 C 扩展依赖（纯 Python 安装）
- 不使用 SQLAlchemy（Round 1 收敛）

## 决策

**选择 `mistune` 作为 MVP 的 Markdown 渲染库**。

## 考虑的替代方案

### 方案 A：`mistune`（采纳）

- ✅ 纯 Python，无 C 扩展，pip install 一键安装
- ✅ 速度快（比 markdown-it-py 快 2~3 倍，benchmarks 公开）
- ✅ API 极简：`mistune.html(text)` 返回 HTML 字符串
- ✅ 活跃维护（2024 年仍有 release），GitHub stars > 5k
- ✅ 支持 GFM（GitHub Flavored Markdown）：表格/任务列表/删除线
- ✅ 安全性：`mistune` 默认禁用原始 HTML，防 XSS
- ❌ 非标准 CommonMark（但 GFM 更适合技术写作者场景）

### 方案 B：`markdown-it-py`

- ✅ 严格 CommonMark 兼容
- ✅ Node.js `markdown-it` 的官方 Python 移植，品牌知名度高
- ❌ 速度慢（比 mistune 慢 2~3 倍）
- ❌ API 复杂（需要实例化 `MarkdownIt()` + `.render()`）
- ❌ 默认不禁用原始 HTML，需手动配置 `typographer` 和 `linkify`

### 方案 C：手写正则解析

- ✅ 零依赖
- ❌ PRD 明确排除（"不手写正则解析 Markdown"）
- ❌ 正确处理嵌套列表/代码块需要数百行代码
- ❌ 无法处理 GFM 特性（表格/任务列表）

## 决定

**采纳方案 A：`mistune`**。

理由：`mistune` 速度最快、API 最简单、安全性最佳（禁用原始 HTML），且 GFM 支持更适合技术写作者场景。`markdown-it-py` 的 CommonMark 兼容性对 MVP 场景无明显价值。

## 后果

### 正面

- ✅ `show` 命令渲染速度有保障（笔记量小但响应快）
- ✅ 渲染输出为 HTML，`click.secho(..., fg="...")` 可着色终端标题/链接
- ✅ 防 XSS 注入（笔记内容中的 `<script>` 不会被渲染）

### 负面

- ❌ 输出是 HTML 而非纯 ANSI 彩色文本（终端渲染需 `click.secho` 支持 HTML 或二次转换）
  - **缓解**：MVP 阶段直接输出 HTML；如终端兼容性问题严重，在 v1.0 backlog 中加 `show --format plain`
- ❌ GFM 特性（任务列表/表格）依赖 mistune 插件机制
  - **缓解**：MVP 只需支持基础标题/列表/链接/代码块，使用内置规则即可

### v1.0 遗留

- `show --format plain`（纯 ANSI 彩色输出）进 v1.0 backlog
- Fenced code block syntax highlighting（进 v1.0 backlog）
