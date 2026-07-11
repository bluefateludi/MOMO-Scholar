# MOMO Scholar Evidence Retrieval Stack Design

日期：2026-07-11  
状态：已确认方向，等待书面规格复核  
适用范围：Evidence Trace 及其后的向量检索与重排阶段

## 1. 决策摘要

MOMO Scholar 先完成 Evidence Trace，再接入百炼 Embedding、可替换向量数据库和百炼 Rerank。Evidence Trace 不依赖外部模型或数据库即可运行；后续检索增强通过接口扩展，不把业务逻辑绑定到 pgvector 或其他具体产品。

执行顺序固定为：

1. Evidence Trace：文本加载、chunk、证据结构、词法检索降级、claim 到 evidence 的引用检查。
2. Vector Retrieval：百炼 Embedding、向量存储抽象、默认本地 pgvector 适配器。
3. Rerank：混合召回、百炼 Rerank、Top-N 到 Top-K 的重排。
4. Generation：百炼生成模型仅消费经过筛选且可追溯的 evidence。

pgvector 是首选本地实现，不是不可替换的架构依赖。如果后续选择 Qdrant、Milvus、Chroma 或托管服务，只替换 `VectorStore` 适配器。

## 2. 目标与非目标

### 2.1 目标

- 每个 `Evidence` 都能追溯到 `paper_id`、`chunk_id`、section/page 和原文。
- 没有百炼 API Key、PostgreSQL 或向量库时，Evidence Trace 仍能通过词法检索工作。
- 百炼统一提供 Generation、Embedding 和 Rerank 能力，但三类模型使用独立接口和配置。
- 向量数据库对上层隐藏建表、索引和查询细节。
- 同一检索评测集能够对比 lexical、vector、hybrid 和 reranked 结果。

### 2.2 非目标

- Evidence Trace 阶段不部署 PostgreSQL，不调用百炼。
- 第一版不建设大规模常驻论文库。
- 不在生成模型中模拟 embedding 或 rerank。
- 不在本阶段锁定最终向量数据库产品。
- 不做复杂分布式索引、分片或多租户权限系统。

## 3. 分阶段架构

```text
Research Question
  -> PDF / Abstract Loader
  -> Chunker
  -> Evidence Candidate Retrieval
       -> LexicalRetriever                 # Evidence Trace 必备、离线可用
       -> VectorRetriever                  # 后续接入
            -> BailianEmbedder
            -> VectorStore
                 -> PgVectorStore          # 默认首选
                 -> OtherVectorStore       # 可替换
  -> Candidate Fusion / Deduplication
  -> BailianReranker                       # 后续接入
  -> Evidence Top-K
  -> Claim Synthesis
  -> Citation Checker
```

默认检索参数：

- 各召回器产生候选，合并去重后保留 `candidate_k=30`。
- Rerank 最终保留 `top_k=8` 个 evidence。
- 参数通过配置注入，测试不得依赖固定线上模型。

## 4. 组件边界

### 4.1 `LexicalRetriever`

输入为 research question 和 `Chunk` 列表，输出带基础相关性分数的 evidence 候选。它是离线基线和所有外部服务失败时的降级路径。

### 4.2 `Embedder`

统一接口接收一批文本并返回同维度向量。`BailianEmbedder` 负责批处理、超时、限流重试和模型维度校验；业务层不直接调用百炼 SDK。

### 4.3 `VectorStore`

最小接口：

- `ensure_collection(vector_size)`：创建或校验索引。
- `upsert(chunks, embeddings)`：按稳定 chunk ID 幂等写入。
- `search(query_embedding, limit, filters)`：返回 chunk ID、分数和 metadata。
- `delete_by_paper(paper_id)`：支持论文重建索引。

metadata 至少保存 `paper_id`、`chunk_id`、section、page、content hash 和 embedding model。

### 4.4 `PgVectorStore`

作为首选本地适配器，实现 `VectorStore`。数据库 schema、距离函数和索引类型只存在于适配器内部。第一版数据量较小时允许精确检索；数据增长后再决定 HNSW/IVFFlat，不提前绑定。

### 4.5 `Reranker`

输入为 question 和候选 chunk 文本，输出稳定 chunk ID 与重排分数。`BailianReranker` 仅负责相关性重排，不生成摘要或结论。

### 4.6 `EvidenceRetriever`

编排 lexical/vector 召回、候选合并、rerank 和 Top-K 截断。它依赖接口而非具体供应商，并记录每个 evidence 的召回来源、原始分数和 rerank 分数。

## 5. 数据与幂等性

- `chunk_id` 是向量记录的稳定主键。
- `content_hash` 用于跳过未变化文本的重复 embedding。
- embedding model 或向量维度变化时，必须使用新 collection/version，禁止混用不同向量空间。
- 删除或更新论文时按 `paper_id` 清理旧 chunk。
- `evidence.json` 始终保存原文和 trace；向量数据库不是唯一事实来源。

## 6. 配置

```env
DASHSCOPE_API_KEY=
BAILIAN_CHAT_MODEL=
BAILIAN_EMBEDDING_MODEL=
BAILIAN_RERANK_MODEL=

VECTOR_STORE_BACKEND=pgvector
VECTOR_STORE_DSN=
VECTOR_COLLECTION=momo_scholar_chunks_v1

RETRIEVAL_CANDIDATE_K=30
RETRIEVAL_TOP_K=8
```

模型名称不写死在代码中。未配置百炼或向量数据库时，pipeline 自动选择 lexical-only；如果用户显式要求 vector-only，则返回清晰配置错误。

## 7. 错误处理与降级

- Embedding 超时或限流：有限次数退避重试；仍失败则本次 run 降级 lexical-only。
- 向量库不可达：记录日志并降级 lexical-only，不阻断 Evidence Trace。
- Rerank 失败：保留融合后的原始排序并标记 `rerank_applied=false`。
- 向量维度不一致：拒绝写入并要求新 collection，禁止静默截断或填充。
- 候选不足：返回已有 evidence，并在报告中标记 insufficient evidence。
- 所有降级路径写入 `logs.jsonl`，同时记录实际采用的 retrieval mode。

## 8. 测试策略

### 8.1 Evidence Trace

- loader 在 PDF 失败时回退 abstract。
- chunk 保留 paper、section/page 和稳定 ID。
- lexical retriever 能把相关 chunk 排在无关 chunk 前。
- citation checker 拒绝不存在的 evidence ID。
- pipeline 在没有任何外部服务时生成 `evidence.json` 和带引用报告。

### 8.2 Vector Retrieval

- 使用内存 fake 实现验证 `VectorStore` 契约。
- `PgVectorStore` 使用独立集成测试，未启动数据库时显式跳过。
- 验证 upsert 幂等、metadata filter、模型版本隔离和维度错误。
- `BailianEmbedder` 使用传输层 fake，不在单元测试调用线上 API。

### 8.3 Rerank

- 验证候选 chunk ID 与重排输出正确关联。
- 验证 Top-N 到 Top-K 截断、平分稳定排序和部分结果处理。
- 使用固定 eval cases 比较 Recall@K、MRR/NDCG 和 rerank 前后提升。

## 9. 验收标准

Evidence Trace 阶段完成时：

- 无 API Key、无数据库也能端到端运行。
- `evidence.json` 包含可追溯 chunk 原文。
- report claim 绑定有效 evidence ID。
- 外部服务接口已预留，但没有引入未使用的数据库依赖。

Vector/Rerank 阶段完成时：

- 百炼 Embedding、百炼 Rerank 和百炼 Generation 分属独立适配器。
- 至少一个 `VectorStore` 实现可用，默认候选为本地 pgvector。
- 更换数据库不影响 `EvidenceRetriever`、synthesis 或 rendering。
- 检索模式、模型名称、候选数、Top-K、延迟和失败降级均可追踪。

## 10. 全局规划影响

现有里程碑保持 Vertical Slice -> Evidence Trace -> Cross-paper Survey -> Eval/Showcase 的主线，但在 Evidence Trace 后新增两个独立阶段：

1. Vector Retrieval Infrastructure。
2. Hybrid Retrieval and Bailian Rerank。

这两个阶段必须晚于离线 Evidence Trace，且不得阻塞无数据库的 MVP 演示。全局实施计划在本规格通过复核后更新。
