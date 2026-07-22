# Embedding、向量与向量检索学习记录

## 本轮学习目标

理解 Embedding、向量、点积、矩阵批处理，以及 RAG 系统中通用的 Indexing 和 Retrieval 两阶段，并区分通用术语与 MOMO Scholar 的项目实现。

## 一、原始理解与纠正

### 原始回答

> Embedding 模型将不同的文本、图片切分成一个一个不同维度的向量，让其能够归类和聚合。VectorStore 是存储被切割的向量，并且当有向量进行检索的时候找出相似向量。

### 准确表述

> Chunker 负责把长文档切成多个 Chunk；Embedding 模型把每个输入映射成一个固定维度的向量，使相似度比较、检索和聚类成为可能。Vector Store 保存 Chunk Embedding、稳定 ID、原始文本和 metadata，并根据 Query Embedding 返回相似候选记录。

需要区分：

```text
切分文本：Chunker / Text Splitter
生成向量：Embedding Model
保存和检索向量：Vector Store
执行聚类：Clustering Algorithm，例如 K-Means
```

同一个 Embedding 模型通常输出固定维度的向量，而不是为不同输入随意生成不同维度。当前 MOMO Scholar 的 Embedder 面向文本；能共同表示文本和图片的模型通常称为 Multimodal Embedding Model。

## 二、向量点积

点积的计算规则是：两个同维向量对应位置相乘，再把乘积相加。

```text
A = [a1, a2, ..., an]
B = [b1, b2, ..., bn]

A · B = a1×b1 + a2×b2 + ... + an×bn
```

学习过程中完成的计算：

```text
查询向量 Q = [1, 2]
Chunk A    = [2, 1]
Chunk B    = [0, 3]

Q · A = 1×2 + 2×1 = 4
Q · B = 1×0 + 2×3 = 6
```

如果只比较原始点积，Chunk B 的分数更高。但原始点积同时受到向量方向和长度影响，因此文本检索中也常使用余弦相似度或归一化向量的点积。

## 三、多行多列的矩阵计算

真实 Embedding 批处理通常使用矩阵：

- 每一行对应一个 Query 或 Chunk；
- 每一列对应 Embedding 的一个维度。

两个三维 Query：

```text
Query 1 = [1, 2, 0]
Query 2 = [0, 1, 2]

Q = [1  2  0]
    [0  1  2]

shape = 2×3
```

三个三维 Chunk：

```text
Chunk A = [2, 1, 0]
Chunk B = [0, 3, 1]
Chunk C = [1, 0, 2]

C = [2  1  0]
    [0  3  1]
    [1  0  2]

shape = 3×3
```

为了让每个 Query 行向量分别与每个 Chunk 行向量计算点积，需要转置 Chunk 矩阵：

```text
Cᵀ = [2  0  1]
     [1  3  0]
     [0  1  2]
```

批量点积：

```text
Q × Cᵀ = [4  6  1]
         [1  5  4]
```

逐项展开：

```text
Query 1 · Chunk A = 1×2 + 2×1 + 0×0 = 4
Query 1 · Chunk B = 1×0 + 2×3 + 0×1 = 6
Query 1 · Chunk C = 1×1 + 2×0 + 0×2 = 1

Query 2 · Chunk A = 0×2 + 1×1 + 2×0 = 1
Query 2 · Chunk B = 0×0 + 1×3 + 2×1 = 5
Query 2 · Chunk C = 0×1 + 1×0 + 2×2 = 4
```

结果矩阵可以读成：

|  | Chunk A | Chunk B | Chunk C |
|---|---:|---:|---:|
| Query 1 | 4 | 6 | 1 |
| Query 2 | 1 | 5 | 4 |

这个例子计算的是原始点积，不是余弦相似度。计算余弦相似度还要除以 Query 和 Chunk 各自的向量长度，或者预先把每个向量归一化为单位向量。

## 四、通用矩阵形状

假设有：

- `m` 个 Query；
- `n` 个 Chunk；
- 每个 Embedding 是 `d` 维。

那么：

```text
查询矩阵 Q：m×d
Chunk 矩阵 C：n×d
转置矩阵 Cᵀ：d×n

Q × Cᵀ = (m×d) × (d×n) = m×n
```

结果矩阵的每个格子表示一组 Query–Chunk 的点积或相似度分数。

## 五、Indexing 与 Retrieval 两阶段

### 原始问题

> 索引和查询两个阶段是 MOMO Scholar 独有的吗，还是通用的？我更希望看到通用 RAG 术语。VectorStore 是自创的吗？

### 准确回答

Indexing 与 Query/Retrieval 是基础 RAG 和向量检索系统中的通用两阶段，不是 MOMO Scholar 独有。

### Indexing / Ingestion

常见中文是索引阶段、数据摄取阶段或知识库构建阶段。

```text
Documents
→ Load / Parse
→ Chunk
→ Embed
→ Index / Upsert into Vector Store
```

这一阶段通常在用户查询之前完成，也常被称为离线阶段。

### Query / Retrieval

常见中文是查询阶段、检索阶段或在线阶段。

```text
User Query
→ Query Embedding
→ Similarity Search
→ Top-K Candidates
→ Optional Rerank
→ Retrieved Context / Evidence
```

## 六、Vector Store 是否为自创术语

`Vector Store` 不是 MOMO Scholar 自创术语，而是 RAG 和语义搜索领域的通用概念。

需要区分：

- **Vector Store**：保存和检索向量记录的通用抽象；
- **Vector Database**：实现向量存储和搜索的具体数据库系统；
- **MOMO Scholar VectorStore**：项目为通用能力定义的 Python Protocol；
- **InMemoryVectorStore**：项目中的内存参考实现，主要用于离线测试。

常见具体产品包括 Qdrant、Milvus、Pinecone、Weaviate，以及 PostgreSQL 的 pgvector 扩展。

## 七、MOMO Scholar 与通用 RAG 术语映射

| 通用 RAG 术语 | MOMO Scholar 对应实现 |
|---|---|
| Document | Paper 及加载后的论文文本 |
| Document Loader | `load_paper_text()` |
| Text Splitter / Chunker | `chunk_text()` |
| Chunk / Node | `Chunk` |
| Embedding Model | `Embedder` |
| Vector Store | `VectorStore` |
| In-Memory Vector Store | `InMemoryVectorStore` |
| Retriever | `VectorRetriever` |
| Query | research question |
| Candidate | `VectorCandidate` |
| Retrieved Evidence | `Evidence` |
| Generated Statement | `Claim` |
| Citation Validation | Citation Checker |

## 八、本轮需要记住的结论

1. Chunker 负责切分，Embedding Model 负责生成固定维度向量。
2. Vector Store 保存向量、文本、稳定 ID 和 metadata，并执行相似度搜索。
3. 点积是对应位置相乘后求和；余弦相似度还会消除向量长度影响。
4. 多个 Query 和 Chunk 可以组成矩阵，通过 `Q × Cᵀ` 批量计算分数。
5. Indexing 和 Retrieval 是通用 RAG 两阶段，不是 MOMO Scholar 独有。
6. Vector Store 是通用术语，MOMO Scholar 只是定义了自己的接口与实现。
7. 向量相似只能说明语义接近，不能保证 Chunk 能够支持最终 Claim。

## 九、下一步问题

1. 向量长度如何计算？
2. 为什么余弦相似度要除以两个向量的长度？
3. 原始点积和余弦相似度会不会产生不同排序？
4. 为什么零向量不能用于余弦相似度？
5. 真实向量数据库为什么需要 HNSW 或 IVF，而不是扫描所有 Chunk？
