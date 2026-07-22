# RAG 中英文专业术语表

## 使用说明

这是一份随 MOMO Scholar 学习进度持续追加的术语表，不追求一次性收录所有 AI 名词。

每个术语尽量回答五个问题：

1. 英文是什么；
2. 中文通常怎么说；
3. 在通用 RAG 系统中是什么意思；
4. 在 MOMO Scholar 中对应什么；
5. 面试中容易出现什么误解。

术语掌握不以“见过英文”为标准，而以能够结合项目解释其输入、输出、职责和边界为标准。

## 一、文档与文本处理

### Document

- **常见中文**：文档、原始文档
- **通用含义**：进入 RAG 系统的原始知识来源，例如 PDF、网页、论文、Word 文件或数据库记录。
- **项目对应**：论文及其加载后的正文或摘要。
- **注意**：通用 RAG 框架中的 `Document` 往往同时包含文本和 metadata；MOMO Scholar 的 `Paper` 更偏论文级领域对象，两者不能机械等同。

### Document Loader

- **常见中文**：文档加载器
- **通用含义**：从 PDF、网页、对象存储或数据库读取原始内容，并转换为系统可以处理的文本或文档对象。
- **项目对应**：`load_paper_text()`。
- **面试关注**：格式解析失败、超时、乱码、PDF 不可用和摘要回退。

### Parser

- **常见中文**：解析器
- **通用含义**：理解外部数据格式并提取结构化内容，例如解析 Atom XML、HTML 或 PDF。
- **项目对应**：arXiv Atom Feed 解析逻辑。
- **注意**：Loader 强调“取得内容”，Parser 强调“理解格式并提取字段”，实际工程中两者有时会合并。

### Chunking

- **其他叫法**：Text Splitting
- **常见中文**：文本切分、分块
- **通用含义**：把长文档拆成适合 Embedding、检索和生成的较小文本单元。
- **项目对应**：`chunk_text()`。
- **面试关注**：Chunk size、overlap、章节边界、语义完整性和 Token 成本。

### Chunk

- **其他框架叫法**：Node、Passage、Segment
- **常见中文**：文本块、分块
- **通用含义**：文档经过切分后形成的最小检索单元。
- **项目对应**：`Chunk` Schema，保留 `chunk_id`、`paper_id`、section、page 和文本等信息。
- **常见误区**：Chunk 不等于 Evidence。Chunk 是相对稳定的内容单元，Evidence 是针对具体查询选出的证据候选。

### Metadata

- **常见中文**：元数据
- **通用含义**：描述一条向量或文档记录的结构化信息，例如来源、文档 ID、页码、作者、时间和权限。
- **项目对应**：`VectorRecordMetadata` 中的 `paper_id`、`chunk_id`、section、page、content hash 和 embedding model。
- **用途**：来源追溯、过滤、权限控制、更新和删除。

## 二、Embedding 与向量基础

### Embedding

- **常见中文**：嵌入、向量表示
- **通用含义**：模型为文本、图片或其他输入生成的固定维度数值表示。
- **项目对应**：当前项目主要处理文本 Embedding。
- **常见误区**：Embedding 不是文本切分；Chunker 负责切分，Embedding 模型负责把每个 Chunk 映射为向量。

### Embedding Model

- **常见中文**：嵌入模型、向量模型
- **通用含义**：把输入转换为向量表示的模型。
- **项目对应**：`Embedder` Protocol 以及百炼 Embedder 适配器。
- **关键约束**：索引和查询必须使用相同模型与兼容版本，不能因为维度相同就混用不同模型。

### Vector

- **常见中文**：向量
- **通用含义**：按顺序排列的一组数字，例如 `[0.2, -0.1, 0.8]`。
- **项目用途**：表示 Chunk 或用户问题在 Embedding 空间中的位置和方向。
- **常见误区**：真实 Embedding 的单个维度通常没有清晰、独立的人类语义。

### Dimension

- **常见中文**：维度
- **通用含义**：一个向量包含的数字数量。
- **例子**：`[1, 2, 3]` 是三维向量。
- **项目约束**：同一 collection 中保存和查询的向量维度必须一致。

### Vector Space

- **常见中文**：向量空间
- **通用含义**：Embedding 模型把输入映射到的数学空间；语义关系通过向量的位置和方向表达。
- **关键理解**：不同 Embedding 模型通常建立不同坐标系，向量不能直接混用。

### Batch

- **常见中文**：批、批次
- **通用含义**：一次性处理多个输入。
- **Embedding 形状**：一批文本通常得到一个 `batch_size × dimension` 的矩阵，每一行对应一个输入的向量。
- **项目对应**：`embed(texts)` 接收文本序列并返回向量列表。

### Matrix

- **常见中文**：矩阵
- **通用含义**：由多行多列数字组成的结构。
- **RAG 用途**：多个 Query 或多个 Chunk 的 Embedding 可以组成矩阵，并通过矩阵运算批量计算相似度。

### Dot Product

- **其他叫法**：Inner Product
- **常见中文**：点积、内积
- **通用含义**：将两个同维向量对应位置相乘后求和。
- **公式**：`A · B = a1×b1 + a2×b2 + ... + an×bn`。
- **例子**：`[1, 2] · [2, 1] = 1×2 + 2×1 = 4`。
- **注意**：原始点积同时受方向和向量长度影响。

### Norm

- **常见中文**：范数、向量长度
- **通用含义**：衡量向量大小。余弦相似度通常使用 L2 Norm。
- **例子**：`[3, 4]` 的 L2 Norm 是 `sqrt(3² + 4²) = 5`。

### Normalization

- **常见中文**：归一化
- **通用含义**：把向量缩放到统一长度，常见做法是除以自身 L2 Norm，使其成为单位向量。
- **用途**：向量归一化后，点积可与余弦相似度等价。
- **注意**：这里的向量归一化不同于论文标题或外部数据的文本标准化。

### Cosine Similarity

- **常见中文**：余弦相似度
- **通用含义**：通过两个向量夹角的余弦值比较方向相似程度。
- **范围**：标准值通常为 `[-1, 1]`。
- **项目对应**：`InMemoryVectorStore` 使用余弦相似度，并映射到 `[0, 1]` 分数范围。
- **常见误区**：相似度高只表示向量接近，不保证文本能够支持某个 Claim。

### Distance Metric

- **常见中文**：距离度量、相似度度量
- **通用含义**：定义如何比较向量，例如 Cosine Similarity、Dot Product 和 Euclidean Distance。
- **注意**：不同数据库可能使用“距离越小越相似”或“分数越大越相似”，必须查看具体定义。

## 三、向量存储与索引

### Vector Store

- **常见中文**：向量存储
- **通用含义**：保存向量、原始文本和 metadata，并提供相似度检索的抽象概念。
- **项目对应**：`VectorStore` Protocol。
- **是否为项目自创术语**：不是，这是 RAG 和语义搜索领域的通用术语；项目只是定义了自己的同名接口。

### Vector Database

- **常见中文**：向量数据库
- **通用含义**：专门或重点支持向量存储、索引、相似度检索和 metadata filter 的数据库系统。
- **常见产品**：Qdrant、Milvus、Pinecone、Weaviate；PostgreSQL 可通过 pgvector 扩展支持向量检索。
- **与 Vector Store 的关系**：Vector Store 是通用抽象，Vector Database 是可能的具体实现。

### Collection

- **其他产品叫法**：Index、Namespace、Table
- **常见中文**：集合、向量集合
- **通用含义**：保存一组兼容向量记录的逻辑容器。
- **项目对应**：`ensure_collection(vector_size)` 创建或校验当前内存集合的维度。
- **注意**：不同产品对 collection 和 index 的命名并不完全一致。

### Index

- **常见中文**：索引
- **通用含义**：组织数据并加速搜索的数据结构，或泛指把知识写入检索系统的过程。
- **两种语境**：`vector index` 可以指 HNSW 等数据结构；`indexing` 可以指完整的数据摄取流程。
- **常见误区**：Index 不一定等于数据库中的一张表。

### Upsert

- **常见中文**：插入或更新
- **来源**：Update + Insert
- **通用含义**：记录不存在时插入，已存在时更新。
- **项目对应**：按稳定 `chunk_id` 写入向量记录，使同一 Chunk 可以更新文本和 metadata。

### Content Hash

- **常见中文**：内容哈希
- **通用含义**：根据内容计算的稳定摘要，可用于判断内容是否变化。
- **项目对应**：对 `chunk.text` 计算 SHA-256，保存到 vector metadata。
- **用途**：支持幂等索引、变更检测和减少重复 Embedding。

### Metadata Filter

- **常见中文**：元数据过滤
- **通用含义**：在相似度检索时，先按结构化字段限制候选范围。
- **项目对应**：`VectorFilter(paper_id=...)`。
- **生产用途**：按论文、用户、租户、时间、语言或权限过滤。

### In-Memory Vector Store

- **常见中文**：内存向量存储
- **通用含义**：只在当前程序内存中保存记录的简单实现。
- **项目对应**：`InMemoryVectorStore`。
- **适用场景**：离线测试、参考实现和小规模实验。
- **限制**：进程结束后数据消失，不适合大规模持久化和生产检索。

## 四、索引与检索流程

### Indexing

- **其他叫法**：Ingestion、Knowledge Base Construction
- **常见中文**：索引阶段、数据摄取、知识库构建
- **通用流程**：`Documents → Load/Parse → Chunk → Embed → Upsert`。
- **项目对应**：`VectorRetriever.index_chunks()`。
- **运行特点**：通常在用户查询之前完成，也常被称为离线阶段。

### Ingestion

- **常见中文**：数据摄取
- **通用含义**：把外部知识读取、清洗、切分并写入检索系统的完整过程。
- **与 Indexing 的关系**：很多资料会混用两者；Ingestion 更强调从外部来源进入系统的全流程。

### Query

- **常见中文**：查询、用户问题
- **通用含义**：用户希望从知识库中寻找答案或相关内容的输入。
- **项目对应**：research question。

### Query Embedding

- **常见中文**：查询向量
- **通用含义**：使用 Embedding 模型把用户 Query 转换得到的向量。
- **关键约束**：必须与被索引的 Chunk Embedding 位于兼容向量空间。

### Retrieval

- **常见中文**：检索、召回
- **通用含义**：根据查询从知识库中找出相关候选内容。
- **常见类型**：Lexical Retrieval、Vector Retrieval、Hybrid Retrieval。
- **项目对应**：词法 Evidence Retriever 和 `VectorRetriever`。

### Retriever

- **常见中文**：检索器
- **通用含义**：接收 Query，编排查询转换、存储搜索、过滤和候选映射的组件。
- **项目对应**：`VectorRetriever`。
- **注意**：Retriever 通常不是数据库本身，而是使用数据库完成业务检索的上层组件。

### Vector Retrieval

- **其他叫法**：Dense Retrieval、Semantic Retrieval
- **常见中文**：向量检索、稠密检索、语义检索
- **通用含义**：通过 Query Embedding 与文档或 Chunk Embedding 的相似度进行召回。
- **优点**：能够发现同义表达和语义改写。
- **限制**：语义相似不等于能够支持最终结论。

### Lexical Retrieval

- **相关术语**：Sparse Retrieval、Keyword Search
- **常见中文**：词法检索、稀疏检索、关键词检索
- **通用含义**：主要利用词项匹配、词频和稀疏表示进行检索。
- **常见算法**：BM25。
- **项目对应**：当前离线 Evidence Retriever 使用确定性的简单词法评分。

### Similarity Search

- **常见中文**：相似度搜索
- **通用含义**：根据指定向量度量，寻找与 Query Vector 最相似的记录。
- **输出**：通常包含记录 ID、文本、metadata 和 similarity score 或 distance。

### Top-K

- **常见中文**：前 K 个结果
- **通用含义**：按照检索分数排序后，保留最高的 K 个候选。
- **项目对应**：`retrieve(question, limit)` 中的 `limit`。
- **取舍**：K 太小可能漏掉相关内容；K 太大会增加噪声、Rerank 和生成成本。

### Candidate

- **常见中文**：候选结果
- **通用含义**：召回阶段得到、尚未完成最终筛选的内容。
- **项目对应**：`VectorCandidate`。
- **常见误区**：Candidate 不是最终 Evidence，更不代表已经能够支持 Claim。

### Score

- **常见中文**：分数、相关性分数
- **通用含义**：检索系统用于排序候选的数值。
- **注意**：不同算法和数据库的 score 含义、方向和范围可能不同，不能直接跨系统比较。

## 五、当前课程中的矩阵形状

当一批 Query 和一批 Chunk 都已经转换为向量时：

```text
Q：m × d
C：n × d
```

其中：

- `m`：Query 数量；
- `n`：Chunk 数量；
- `d`：Embedding 维度。

批量计算点积：

```text
Q × Cᵀ = (m × d) × (d × n) = m × n
```

结果矩阵中：

- 每一行对应一个 Query；
- 每一列对应一个 Chunk；
- 每个格子对应这一组 Query–Chunk 的相似度分数。

真实向量数据库通常使用 HNSW、IVF 等索引减少需要精确比较的候选数量，而不是每次暴力扫描全部记录。

## 六、待后续课程追加

以下术语将在对应单元学习后补充，不在当前阶段提前堆砌定义：

- Hybrid Retrieval
- Fusion
- Reciprocal Rank Fusion（RRF）
- Reranker / Cross-Encoder
- Recall@K、Precision@K、MRR、nDCG
- Retrieved Context
- Generation
- Grounding
- Faithfulness
- Claim–Evidence Entailment
- Agent State、Tool、Action、Observation 和 Control Loop

