# tag rename - 产品需求文档

> **Task ID:** t_20260620_9278f7
> **作者:** PM Agent
> **创建时间:** 2026-06-20T15:05:00+08:00
> **辩论轮次:** 3 轮（product-champion / tech-reviewer / devil-advocate / quality-gatekeeper）
> **状态:** 已通过辩论收敛

---

## 用户故事

- 作为 mdnotes 用户，我想要一条命令 `mdnotes tag rename <old> <new>`，以便在不需要手动搜索替换的情况下，系统性地更新我所有笔记中的 tag 引用，避免遗漏和误改。
- 作为有大量笔记的用户，我想要 `mdnotes tag rename --dry-run`，以便在正式执行前确认改动范围（影响哪些文件、数量多少），避免误操作。
- 作为在 CI/CD 脚本中使用 mdnotes 的用户，我想要 rename 命令没有交互式 prompt，以便自动化脚本可以可靠执行。

## 业务流程

1. 用户执行 `mdnotes tag rename <old> <new>`（可选加 `--dry-run`）
2. CLI 解析参数，校验 `<old>` 和 `<new>` 非空且不相等
3. **Pre-flight 检查**：查询 db 获取所有含 `<old>` tag 的文件列表；检查每个文件是否可写（权限、锁）；若任一文件不可写，提前失败并列出文件名
4. 若加了 `--dry-run`：输出「将影响 <N> 个文件：[file1, file2, ...]」，不写 db 不写文件，退出
5. 若未加 `--dry-run`：
   a. db transaction begin
   b. 对每个文件：rewrite frontmatter 中的 tag 列表（`old` → `new`），先写 .tmp 再 rename（原子性）
   c. 所有文件 rewrite 成功后：`UPDATE tags SET name = ? WHERE name = ?`，commit
   d. 任一文件失败：db rollback + 输出失败文件列表，退出 code 1
6. 成功时输出「Renamed tag '<old>' → '<new>' in <N> file(s).」

## 业务价值 / ROI

- **解决的问题：** 消除手动 tag 重命名的易错性和重复劳动；支持 tag 体系随知识库演化自然调整；防止用户因 tag 维护负担放弃工具。
- **预期收益：** 减少 tag 体系维护的人工操作时间；提升 mdnotes 留存率（tag 生命周期管理是 blocking gap）；通过 dry-run 防止误操作导致的数据损坏。
- **优先级：** P1（高优先级便利性功能；tag rename 是 tag 生命周期管理的最后一块拼图）

---

## 范围边界

### 包含
- `mdnotes tag rename <old> <new>` 命令（argparse subcommand）
- `--dry-run` / `--check` 标志（简化版：只显示文件数量 + 列表）
- `--help` 完整用法示例
- Pre-flight 可写性检查（权限、锁）
- 批量操作警告（受影响文件数 > 10 时提示）
- 近似 tag 建议（当 `<old>` 不存在时，提示 did you mean 'XXX'?）

### 不包含
- 完整 diff dry-run（v1.1 迭代，显示每个文件的前后 YAML diff）
- 全局 rename（跨项目作用域；另起 task 处理）
- 文件系统层面的完整原子性回滚（v1.1 改进）
- rename 操作的事务性日志（审计需求；不在 MVP scope）
- glob 模式过滤（只 rename 某目录下文件的 tag）

---

## 验收标准（业务层面）

- [ ] `mdnotes tag rename foo bar` 成功时返回 exit code 0，输出「Renamed tag 'foo' → 'bar' in <N> file(s).」
- [ ] `mdnotes tag rename foo bar --dry-run` 不写 db 不写文件，只输出受影响文件数量和列表
- [ ] `<old>` tag 不存在时返回 exit code 1，stderr 输出「Tag '<old>' not found」
- [ ] `<old>` 不存在但有近似 tag 时，提示「Tag '<old>' not found, did you mean '<suggestion>'?」
- [ ] `<old>` 和 `<new>` 相同时输出「Old and new tag are identical, nothing to do.」并 exit 0
- [ ] `<old>` 存在且 `<new>` 也存在时：强制覆盖，输出「Tag '<new>' already exists, merging references」
- [ ] 受影响文件数 > 10 时输出警告「This will rename <N> files. Use --dry-run to preview.」
- [ ] 任一文件 frontmatter 写回失败时：db rollback，exit code 1，输出失败文件列表
- [ ] 所有文件可写性检查失败时（Pre-flight）：提前失败，列出不可写文件，不做任何修改

---

## 关键约束（辩论共识）

1. **tag 大小写策略**：SQL 层 `WHERE name = ?`（case-sensitive 精确匹配）；rename 后 new tag 保持用户输入的大小写形式。若 `<old>` 大小写不匹配，报「not found」并给出近似建议。
2. **db 作用域**：rename 作用于**当前项目**（cwd 下的 mdnotes.db），不支持全局 rename。
3. **dry-run MVP 简化版**：只显示「文件数量 + 列表」，不显示 diff。完整 diff 作为 v1.1 迭代。
4. **Pre-flight 强制检查**：执行前检查所有目标文件是否可写，不可写则提前失败。
5. **部分失败处理**：db rollback + 失败列表报告。MVP 不支持文件系统层面自动回滚（race condition 下 backup/restore 不可靠）。
6. **无交互式 prompt**：CI/CD 友好，overwrite 策略不询问确认。
7. **原子性写**：文件 frontmatter rewrite 采用「写 .tmp → rename」保证 write-atomic。
8. **CHANGELOG + help 文档**：不可逆操作提示；overwrite 策略明确说明。

---

## 风险提示

- **数据一致性风险**：MVP 的回滚边界是「db rollback + 失败文件列表」，不包含文件系统自动恢复。若文件 rewrite 成功但后续 db rollback（极端 race condition），文件已是新 tag 但 db 回滚到旧状态，产生不一致。**缓解**：Pre-flight 检查降低运行时失败率；文档诚实说明回滚边界。
- **隐式破坏性**：rename 影响 N 个文件，N 可能很大（>100）。**缓解**：dry-run 是 MVP 必须；批量警告强制显示。
- **大小写歧义**：Unix FS 大小写敏感，frontmatter tag 比较默认 case-sensitive。**缓解**：报错信息提供近似 tag 建议。
- **concurrent rename**：多实例同时 rename 同一 tag，WAL 排他锁保护 db，文件系统层无锁。**接受风险**：单用户本地工具，非多用户服务端场景。
- **API 契约缺失**：mdnotes 作为 Python CLI，错误处理（exit code vs 异常）需在 spec 中明确（Architect 负责）。
