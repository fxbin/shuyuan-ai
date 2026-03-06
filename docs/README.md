# ShuYuanAI Docs 导航与治理约定

## 1. 文档分工

- `1.0.md`：v1 设计基线（历史版本，不作为 v2 新实现的权威契约）。
- `2.0.md`：v2 架构总览与治理目标（面向决策与全局设计）。
- `v2.0-detail.md`：v2 规则细则（路由、预算、降级、事件流、产物模板）。
- `v2.0-schema.md`：v2 数据契约（Envelope 与各 artifact body schema）。
- `v2.0-extractors.md`：御史台 Extractor/Runner 的实现细化与伪代码。

## 2. 权威顺序（冲突处理）

当多个文档描述冲突时，按以下优先级覆盖：

1. `v2.0-schema.md`
2. `v2.0-detail.md`
3. `v2.0-extractors.md`
4. `2.0.md`
5. `1.0.md`

## 3. 一致性硬规则

- 所有证据锚点字段统一使用 `json_pointer`（RFC 6901）。
- 所有 Envelope 必须包含 `header.artifact_type`。
- 从 Phase 1 开始，启用 strict envelope（按 `artifact_type` 绑定 body schema）。
- 新增 artifact_type 时，必须同时更新：
  - `v2.0-schema.md` 的 `artifact_type enum`
  - strict envelope 的绑定规则
  - 对应 body schema
  - `v2.0-detail.md` 产物模板

## 4. 版本维护建议

- 文档改动采用“先契约后流程后实现说明”顺序：
  1. 先改 `v2.0-schema.md`
  2. 再改 `v2.0-detail.md`
  3. 最后改 `v2.0-extractors.md` 与 `2.0.md`
- 每次版本迭代至少执行一次跨文档字段一致性检查（artifact_type、stage、citations、预算字段）。
