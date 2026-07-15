# Hybrid Retrieval Design

日期：2026-07-15
状态：用户已批准，待规格审查
阶段：Vector Retrieval Infrastructure 之后，Bailian Rerank 之前

## 1. 决策摘要

MOMO Scholar 第一版 Hybrid Retrieval 同时运行离线词法召回与文本向量召回，使用 Reciprocal Rank Fusion（RRF）按稳定 `chunk_id` 合并、去重和排序，再把 Top-K 候选转换成当前 run 的 `Evidence`。

核心验收标准是：离线可测、融合确定；`auto` 模式遇到预期的向量服务可用性故障时可靠降级为 lexical-only；契约或编程错误不得被降级逻辑吞掉。

## 2. 背景

现有 Evidence Trace 使用词项重叠排序 chunk，适合模型名、缩写、数字和精确术语，但可能漏掉措辞不同、语义相近的内容。现有 Vector Retrieval 能通过 Embedding 找到语义候选，但可能弱化精确词项，也尚未接入 Evidence Trace pipeline。

Hybrid Retrieval 利用二者互补性：lexical 提供精确匹配与离线基线，vector 提供语义召回，fusion 在不直接比较异构原始分数的前提下形成统一候选序列。

## 3. 目标与非目标

目标：

- 为 lexical 与 vector 定义统一、可追溯的候选契约。
- 保持现有 `retrieve_evidence()` 的可观察行为和离线兼容性。
- 使用 1-based rank 的 RRF 融合候选。
- 保留来源、各路原始分数、各路排名和融合分数。
- 支持 `auto`、`lexical`、`hybrid` 三种模式。
- 把实际模式、候选数量和安全降级原因写入 `logs.jsonl`。
- 扩展 Evaluation Control，比较 Recall@K、Precision@K、MRR、nDCG@K。

非目标：

- 不实现 Bailian Rerank、LLM 排序或 Generation。
- 不实现 pgvector/Qdrant 等持久化向量存储适配器。
- 不加入学习型融合、动态权重或基于 fixture 的调参。
- 不改变 synthesis、citation checker 或 renderer 的职责。
- 不记录 API Key、embedding、论文原文或供应商响应正文。
- 不承诺 Hybrid 在每个 case 的每项指标都优于所有单路召回。

## 4. 融合算法

采用 RRF，因为词法重叠分数与向量相似度不具备相同统计含义，直接加权求和需要额外归一化与调参。

```text
raw_rrf(chunk) = Σ source_weight / (rrf_k + rank_source(chunk))
```

规则：

- rank 从 1 开始；lexical/vector 默认权重均为 `1.0`。
- 默认 `rrf_k=60`，必须为正整数。
- 缺席某一路的候选不获得该路贡献。
- 相同 `raw_rrf` 时按 `chunk_id` 升序。
- 第一版不开放 source weight 配置。

为满足 `Evidence.relevance_score` 的 `[0, 1]` 契约：

```text
max_rrf = Σ active_source_weight / (rrf_k + 1)
normalized_fusion_score = clamp(raw_rrf / max_rrf, 0, 1)
```

该分数只用于同一次 run 内排序和展示。不同实际模式之间不声明可直接比较，日志必须记录 `actual_mode`。

## 5. 架构与组件

```text
question + chunks
    ├── LexicalCandidateRetriever ──┐
    └── VectorCandidateSource ──────┤
                                    v
                         HybridEvidenceRetriever
                         merge -> RRF -> stable Top-K
                                    v
                    analysis -> synthesis -> citation check
```

### 5.1 RetrievalCandidate

新增不可变且禁止额外字段的统一候选模型，建议位于 `paper_agent/evidence/models.py`：

```text
chunk_id, paper_id, text, section, page
retrieval_sources
lexical_score, lexical_rank
vector_score, vector_rank
fusion_score
```

`retrieval_sources` 使用固定顺序元组。存在某一路 source 时，对应 score/rank 必须同时存在且 rank >= 1。相同 `chunk_id` 的 paper、text 或 provenance 不一致属于契约错误。

### 5.2 Lexical candidate retrieval

从 `retrieve_evidence()` 提取纯函数 `retrieve_lexical_candidates(question, chunks, limit)`。它不创建 evidence ID、不依赖 run ID，保留当前 tokenization、过滤、分数和 `(-score, chunk_id)` 排序。

现有 `retrieve_evidence()` 保持兼容层：调用新候选函数，再按原逻辑生成 run-scoped Evidence。原 Evidence Trace 结果不得改变。

### 5.3 Vector candidate source

现有 `VectorRetriever` 保持向量领域接口。新增窄适配器把 `VectorCandidate` 映射为统一候选，并负责当前 run 的索引和查询。

适配器只能把明确的外部可用性故障转换为 `RetrievalSourceUnavailable`，例如 Embedding timeout、HTTP/API transport failure、未来数据库连接不可达。维度或模型身份不一致、重复 chunk 身份、非法 metadata 和参数错误必须原样抛出。

### 5.4 HybridEvidenceRetriever

职责顺序：

1. 校验 question、run_id、candidate/top/RRF K。
2. 运行 lexical source，最多取 `candidate_k`。
3. 按模式决定是否运行 vector source。
4. 按 `chunk_id` 合并并验证身份。
5. 计算 RRF、稳定排序并截取 `top_k`。
6. 生成 `run_id:ev_NNN` Evidence。
7. 返回 Evidence 与结构化 diagnostics。

组件不读取环境变量、不创建 HTTP client、不渲染报告；依赖通过构造参数注入。

### 5.5 Pipeline assembly

独立 factory 根据 Settings 组装模式：

- `lexical`：仅离线词法路径。
- `auto`：没有有效 DashScope API Key 时 lexical；配置有效时尝试 hybrid。
- `hybrid`：要求有效 vector 配置，缺失时立即返回清晰配置错误。

第一版使用现有 `InMemoryVectorStore` 完成每个 run 的索引与查询，不宣传为持久化数据库能力。未来数据库适配器只替换 vector source 内部组装。

## 6. 配置

```env
RETRIEVAL_MODE=auto
RETRIEVAL_CANDIDATE_K=30
RETRIEVAL_TOP_K=8
RETRIEVAL_RRF_K=60
```

mode 规范化后只接受 `auto|lexical|hybrid`。三个 K 均须为正整数。`candidate_k < top_k` 时不隐式改写配置，最终返回已有候选。

## 7. 模式与降级

| requested | 条件 | actual | 行为 |
|---|---|---|---|
| lexical | 任意 | lexical | 不调用 vector |
| auto | vector 未配置 | lexical | 正常离线路径 |
| auto | vector 成功 | hybrid | RRF 融合 |
| auto | availability failure | lexical | 记录安全降级码 |
| hybrid | vector 未配置 | 无 | 配置错误 |
| hybrid | availability failure | 无 | 明确失败，不降级 |
| 任意 | contract/programming error | 无 | 原样失败 |

Lexical 是可靠基线；lexical 自身的契约或程序错误不能伪装成空结果。

## 8. 可观测性

新增不可变 `RetrievalDiagnostics`：

```text
requested_mode, actual_mode
lexical_candidate_count, vector_candidate_count
fused_candidate_count, returned_evidence_count
vector_attempted, degraded, degradation_code
```

`logs.jsonl` 写一条结构化 retrieval event。`degradation_code` 使用稳定枚举，例如 `embedding_timeout`、`vector_transport_unavailable`，不包含秘密、原文或供应商响应。

## 9. Evaluation Control 扩展

新增纯检索排序指标：

- Recall@K：Top-K 命中的唯一相关 chunk 数 / 唯一相关 chunk 总数。
- Precision@K：Top-K 中相关结果数 / 实际返回长度；空结果为 0。
- MRR：首个相关 chunk 的倒数排名；无命中为 0。
- nDCG@K：`2^grade - 1` gain 与 `log2(rank + 1)` discount；理想 DCG 为零时返回 0。

新 fixture 包含 `case_id`、`query`、`chunks`、`relevance_by_chunk_id`。离线比较器用同一 case 分别运行 lexical、确定性 fake-vector 和 hybrid，输出逐 case与汇总指标。

fixture 覆盖 lexical 独有命中、vector 独有命中、重复命中、无相关结果、分级相关性和平分排序。验收要求 Hybrid 在互补 case 中保留两路相关结果，指标如实暴露提升或退化；不得据此调整 source weight。

## 10. 测试策略

单元测试：

- candidate 模型校验、不可变性与身份一致性。
- lexical candidate 排序与旧 API 兼容。
- RRF 数学、去重、空 source 和稳定 tie-break。
- mode/K 参数校验。
- 四项排序指标的正常与边界行为。

编排与降级测试：

- active source 每次只调用一次，并接收正确 candidate K。
- top K 只在融合后截断。
- `auto` 只对 `RetrievalSourceUnavailable` 降级。
- 强制 `hybrid` 不降级。
- ValueError、维度和 metadata 错误不会被吞掉。
- diagnostics 与实际路径一致。

集成与回归测试：

- fake embedder + InMemoryVectorStore 离线 Hybrid 集成。
- 无 API Key 的 pipeline 继续生成 evidence、报告与 retrieval log。
- 注入 fake vector source 的 pipeline 生成融合 Evidence。
- 现有 231 项基线与新增测试全部通过。
- 正常测试不访问网络。

## 11. 文件职责建议

```text
paper_agent/evidence/models.py          # candidates and diagnostics
paper_agent/evidence/retriever.py       # lexical candidates + compatibility
paper_agent/evidence/hybrid.py          # RRF and orchestration
paper_agent/evidence/vector_source.py   # vector adapter/error mapping
paper_agent/evidence/factory.py         # Settings-to-retriever assembly
paper_agent/eval/metrics.py             # ranking metrics
paper_agent/eval/runner.py              # offline comparison
paper_agent/config.py                   # mode/top-k/RRF settings
paper_agent/pipeline.py                 # retrieval injection and log write
```

不得把 factory、RRF 和外部错误映射堆入 pipeline。

## 12. 兼容性与限制

- `Chunk`、`Evidence`、`VectorCandidate` 字段不变。
- `retrieve_evidence()` 参数和确定性输出不变。
- 默认 `auto` 在无 API Key 时等价于当前 lexical-only。
- InMemoryVectorStore 不跨进程持久化，每个 run 可能重新 embedding/index。
- content hash 已存 metadata，但本阶段不实现 embedding 前持久化跳过。
- RRF 不使用原始分数幅度；当前 lexical tokenizer 对非 ASCII 支持有限。

## 13. 验收标准

1. 三种路径可用 fake 依赖完全离线验证。
2. Hybrid 按稳定 chunk ID 去重，RRF 排序确定且可追溯。
3. 原 Evidence Trace 公开行为保持兼容。
4. `auto` 仅对预期 vector availability failure 降级；强制 `hybrid` 明确失败。
5. 契约错误不静默降级。
6. pipeline 输出有效 run-scoped Evidence ID 与安全 diagnostics。
7. Evaluation Control 可比较三种模式的四项排序指标。
8. 正常测试无网络依赖，完整回归通过。
9. 不包含 Rerank、Generation 或持久化数据库实现。

## 14. 后续阶段

Hybrid Retrieval 独立验收后，再创建 Bailian Rerank 规格与计划。Rerank 消费融合后的 Top-N，输出 Top-K Evidence；失败时可回退到本规格定义的 fused order，而不改变 lexical、vector 或 RRF 契约。
