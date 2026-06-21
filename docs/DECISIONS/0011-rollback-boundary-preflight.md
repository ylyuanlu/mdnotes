# ADR-0011 — tag rename 回滚边界 + Pre-flight 可写性检查

> **日期**：2026-06-20
> **状态**：Accepted
> **适用版本**：v1.5.0+
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/03-tag-rename.md` `docs/SPEC/03-tag-rename-command.md`

## 背景

PM 辩论中 Quality Gatekeeper 指出「若文件 rewrite 成功但后续 DB rollback（极端 race condition），文件已是新 tag 但 DB 回滚到旧状态，产生不一致」。最终仲裁：
1. Pre-flight 强制可写性检查（降低运行时失败率）
2. 回滚边界明确：db 可回滚，文件系统回滚 MVP 诚实说局限

## 决策

**Pre-flight 强制检查所有目标文件可写性；db transaction 失败时 rollback；文件系统层面回滚不在 MVP scope，文档诚实说明局限**。

## 考虑的替代方案

### 方案 A：完整原子性回滚（db + 文件系统）（未采纳）

- ✅ 极端 race condition 下数据一致性最高
- ❌ 实现复杂度高：需要先 backup 所有文件，失败时 restore
- ❌ backup/restore 在跨文件系统 rename 时不可靠（`shutil.copy2` 可能中途失败）
- ❌ 破坏性操作（rename 100+ 文件）的 rollback 风险由用户承担更合理
- ❌ 单用户本地工具，race condition 概率极低

### 方案 B：Pre-flight 检查 + db rollback + 诚实说明局限性（采纳）

- ✅ Pre-flight 检查消除绝大多数运行时失败（文件权限、锁）
- ✅ db transaction rollback 有 SQLite 原子性保证（`BEGIN IMMEDIATE` + `COMMIT/ROLLBACK`）
- ✅ 实现成本低，Phase 1/2/3 天然形成
- ✅ 用户在 CLI help 和 CHANGELOG 中明确知晓回滚边界
- ❌ 极端 race condition（文件 rewrite 后 DB rollback）仍有数据不一致风险
  - 缓解：Pre-flight 检查降低失败率；文档诚实说明「MVP 不包含文件系统自动回滚」

## 拒绝方案 A 的理由

方案 A 的 backup/restore 在以下场景不可靠：
1. 文件在 NFS/网络文件系统上，`shutil.copy2` 可能中途超时
2. 100+ 文件的 backup/restore 本身可能失败（disk full、permission）
3. `os.rename()` 在跨文件系统时不可用（需要 `shutil.move`，增加复杂性）

MVP 接受「db rollback 但文件系统依赖 Pre-flight 检查」作为平衡点。

## 后果

### 正面

- ✅ Pre-flight 在真实 rename 之前拦截不可写文件，避免部分写入后 rollback
- ✅ db transaction 原子性保证：要么全成功，要么全回滚
- ✅ 用户知晓回滚边界，不产生错误预期

### 负面

- ❌ 极端 race condition 下存在数据不一致窗口
  - 缓解：文档诚实说明；Pre-flight 降低运行时失败率
- ❌ 文件 rewrite 成功但 db rollback 时，用户需要手动恢复文件
  - 缓解：CHANGELOG 说明「受影响文件已修改，建议手动比对」