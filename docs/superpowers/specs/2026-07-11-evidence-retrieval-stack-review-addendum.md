# Evidence Retrieval Stack Review Addendum

本附录记录 `2026-07-11-evidence-retrieval-stack-design.md` 通过规格审查后的非阻断澄清，与主规格共同构成后续实施计划的输入。

## 1. 离线 Evidence Trace

Evidence Trace 的验收不依赖后续百炼 Generation。无 API Key、无数据库时，报告使用确定性模板或抽取式 synthesis，claim 仍必须绑定有效 evidence ID。

## 2. 最小数据字段

- `Chunk` 至少包含 `chunk_id`、`paper_id`、text 和 token count。
- PDF 来源保留 section/page；abstract fallback 时 section 可设为 `Abstract`，page 为 `null`。
- `Evidence` 至少包含 `evidence_id`、`paper_id`、`chunk_id`、quote 和 relevance score。
- 后续阶段可附加 retrieval source、vector score 和 rerank score。
- report claim 通过 `evidence_ids` 引用 evidence；不存在或跨 run 的 ID 必须标记为 unsupported。

## 3. 可替换向量存储契约

`VectorStore.search` 使用项目内定义的 typed filter object，不暴露具体数据库查询语法。各适配器必须把距离或相似度转换为统一的 `[0, 1]` 相关性分数，且数值越大表示越相关。

## 4. 严格阶段顺序

先验证 vector retrieval 独立工作，再引入 lexical + vector 的 hybrid fusion，最后接入 Bailian Rerank。不得在 Evidence Trace 阶段提前引入数据库或线上模型依赖。
