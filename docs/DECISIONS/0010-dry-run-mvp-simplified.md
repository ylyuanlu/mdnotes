# ADR-0010 — tag rename dry-run MVP 简化版：文件列表+数量（不含 diff）

> **日期**：2026-06-20
> **状态**：Accepted
> **适用版本**：v1.5+
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/03-tag-rename.md` `docs/SPEC/03-tag-rename-command.md`

## 背景

PM 辩论中 Tech Reviewer 主张 dry-run 应显示完整 YAML diff（前/后对比），以避免 frontmatter rewrite 格式破坏。PM 仲裁决定 MVP 阶段先做简化版（只显示文件数量+列表），完整 diff 留到 v1.1 迭代。

## 决策

**dry-run MVP 只输出受影响文件数量和文件列表，不显示 diff**。

## 考虑的替代方案

### 方案 A：dry-run 显示完整 diff（前/后 YAML 对比）（未采纳）

- ✅ 用户可看到 frontmatter rewrite 后的精确结果，避免格式破坏
- ❌ 实现成本高：需要 diff 库（如 `unified_diff`）+ 格式化输出
- ❌ MVP 交付时间增加
- ❌ v1.0 用户主要是验证"影响范围"，完整 diff 是增强需求

### 方案 B：dry-run 只显示文件数量+列表（采纳）

- ✅ 实现成本低，Phase 1 可独立完成
- ✅ 用户最核心需求是「确认改动范围」，文件列表已满足
- ✅ 快速交付，收集真实用户反馈后再做 diff
- ❌ 无法预览 frontmatter rewrite 后的格式（接受：v1.1 补齐）

## 决定

**采纳方案 B**。

理由：MVP 应最小化交付成本，文件列表已覆盖核心验证需求；diff 作为 v1.1 迭代项优先级更低。

## 后果

### 正面

- ✅ Phase 1 可独立交付，dev 无需引入 diff 依赖
- ✅ 用户快速得到「影响范围」信息，防止误操作
- ✅ 简化测试：只需验证「dry-run 不修改任何数据」

### 负面

- ❌ 用户看不到 frontmatter rewrite 后的格式变化，可能导致格式意外破坏（Markdown 格式问题）
  - 缓解：v1.1 实现 diff 输出，或在批量警告中提示「建议先 --dry-run」
- ❌ 文件列表很长时（>100 文件）输出冗长
  - 缓解：Phase 3 限制输出长度，或分页