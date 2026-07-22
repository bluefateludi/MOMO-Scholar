# Embedding、向量与向量检索：主体课程

## 单元结构

```text
1. Embedding 是什么
2. 向量和维度是什么
3. 向量空间如何表示语义
4. Embedding Model 与 Vector Store 的职责
5. 为什么必须使用同一个 Embedding 模型
6. 余弦相似度如何工作
7. 项目的分数映射
8. Chunk 如何建立索引并被检索
9. Embedding 返回值为什么需要校验
10. 本阶段掌握检查
```

本文件记录第二单元的主体课程。后续原始回答、理解纠正、点积与矩阵练习，以及通用 RAG 术语映射，记录在同目录的 `embedding-vector-retrieval-learning-log.md`。

## 一、Embedding 是什么

Embedding 可以翻译为“嵌入”或“向量表示”。它把文本转换成一组可以参与数学计算的数字，使计算机能够比较文本之间的语义相似程度。

```text
“猫正在睡觉”
→ Embedding Model
→ [0.21, -0.42, 0.73, 0.16, ...]

“一只小猫在休息”
→ Embedding Model
→ [0.19, -0.39, 0.76, 0.14, ...]
```

两句话用词不同但语义接近，因此模型生成的向量通常也比较接近。“数据库正在执行索引扫描”与前两句话语义不同，其向量方向通常相差更大。

完整过程是：

```text
文本
→ Embedding Model
→ Vector
→ Similarity Computation
```

### Embedding 不是简单的关键词统计

Embedding 模型不是简单记录“猫出现一次、睡觉出现一次”。现代模型会从大量文本中学习上下文和语义关系，因此有机会识别：

- 同义词与近义表达；
- 句子改写；
- 上下位概念；
- 部分跨语言关系；
- 主题和语境关系。

例如：

```text
如何降低大模型幻觉？

External evidence can improve factual reliability.
```

两句话没有直接共享关键词，但 Embedding 模型可能学习到：

```text
降低幻觉 ≈ 提高事实可靠性
```

于是把它们映射到向量空间中相近的位置。

## 二、向量、维度与分布式语义表示

向量可以先理解为一个有序数字列表：

```python
[0.12, -0.35, 0.81]
```

它包含三个数字，因此是三维向量。

```python
[0.12, -0.35, 0.81, 0.44]
```

它包含四个数字，因此是四维向量。真实 Embedding 模型可能产生几百维、上千维或更多维的向量。

### 每一个数字代表什么

不能简单地把每个维度解释成：

```text
第一维表示动物
第二维表示数据库
第三维表示情绪
```

更准确的理解是：

> Embedding 向量是模型学习得到的分布式语义表示。单独一个维度通常没有明确的人类语义，语义信息分散在多个维度之间，需要结合整个向量的位置和方向理解。

## 三、向量空间的直观理解

为了教学，可以使用二维向量模拟两个语义方向：

```text
事实可靠性方向：[1, 0]
性能效率方向：  [0, 1]
```

三个 Chunk：

```text
Chunk A：Grounding reduces hallucinations.
向量：[1, 0]

Chunk B：Retrieved evidence improves factual reliability.
向量：[1, 0]

Chunk C：Caching improves throughput.
向量：[0, 1]
```

用户问题：

```text
How is factual reliability improved?
查询向量：[1, 0]
```

查询与 A、B 方向一致，与 C 方向不同：

```text
Query  [1, 0]
Chunk A [1, 0] → 非常相似
Chunk B [1, 0] → 非常相似
Chunk C [0, 1] → 不相似
```

### 项目中的确定性 Fake Embedder

MOMO Scholar 的离线集成测试使用了这种简化向量，而没有调用真实线上模型：

```python
vectors = {
    factual_a.text: [1.0, 0.0],
    factual_b.text: [1.0, 0.0],
    efficiency.text: [0.0, 1.0],
    "How is factual reliability improved?": [1.0, 0.0],
}
```

这样可以稳定验证向量检索流程：

- 不依赖网络；
- 不消耗线上模型额度；
- 相同输入得到确定结果；
- 不受供应商模型输出变化影响；
- 能精确构造相关和不相关向量。

## 四、Embedding Model 不等于 Vector Store

Embedding Model 负责：

```text
文本 → 向量
```

Vector Store 负责：

```text
保存向量
+ 保存 Chunk 文本、稳定 ID 和 metadata
+ 根据 Query Vector 搜索相似记录
```

完整过程：

```text
Chunk Text
→ Embedding Model
→ Chunk Embedding
→ Vector Store

User Query
→ 同一个 Embedding Model
→ Query Embedding
→ Similarity Search
→ Candidate Chunks
```

生活类比：

- Embedding Model 像地图绘制器，负责给文本确定坐标；
- Vector Store 像地图系统，负责保存坐标并寻找附近的位置；
- Distance Metric 决定“距离近”具体如何计算。

## 五、为什么 Query 和 Chunk 必须使用同一个模型

不同 Embedding 模型可能建立不同的向量坐标系：

```text
模型 A：
事实可靠性 → [1, 0]
性能效率   → [0, 1]

模型 B：
事实可靠性 → [0, 1]
性能效率   → [1, 0]
```

如果 Chunk 使用模型 A：

```text
事实可靠性 Chunk → [1, 0]
```

但 Query 使用模型 B：

```text
事实可靠性 Query → [0, 1]
```

同一语义在不同坐标系中变成不同方向，比较结果失去意义。

MOMO Scholar 因此检查：

```python
if self._embedder.model_name != self._store.embedding_model:
    raise ValueError(
        "embedder and store embedding model identities must match"
    )
```

这条校验保护的关键前提是：

> 只有来自同一个兼容向量空间的向量，才可以直接比较。

即使两个模型都输出 1024 维向量，也不能说明它们属于同一个向量空间。

## 六、余弦相似度

Cosine Similarity 主要比较两个向量的方向，而不是单纯比较绝对长度。

```text
cosine(A, B) = (A · B) / (||A|| × ||B||)
```

其中：

- `A · B`：两个向量的点积；
- `||A||`：向量 A 的长度；
- `||B||`：向量 B 的长度。

标准结果通常位于 `[-1, 1]`：

```text
 1 → 方向完全一致
 0 → 两个方向正交
-1 → 方向完全相反
```

### 示例一：方向相同

```text
A = [1, 0]
B = [1, 0]

A · B = 1×1 + 0×0 = 1
cosine = 1 / (1×1) = 1
```

### 示例二：方向正交

```text
A = [1, 0]
B = [0, 1]

A · B = 1×0 + 0×1 = 0
cosine = 0
```

### 示例三：长度不同但方向相同

```text
A = [1, 0]
B = [10, 0]
```

两者长度不同，但方向完全一致，因此余弦相似度仍然是 1。

余弦相似度的重要特点是：

> 它更加关注向量方向，而不是绝对长度。

## 七、项目为什么把分数转换到 0～1

标准余弦相似度可能位于 `[-1, 1]`。MOMO Scholar 的 `InMemoryVectorStore` 使用：

```python
score = (cosine + 1.0) / 2.0
```

映射关系：

```text
cosine = -1 → score = 0
cosine =  0 → score = 0.5
cosine =  1 → score = 1
```

这样让 `VectorSearchResult.score` 始终位于 `[0, 1]`，数据契约更直观。

但必须注意：

> 项目中的 `score = 0.5` 不一定代表“中等相关”，它可能只是原始余弦值为 0。不能脱离评分定义解释业务含义。

## 八、从 Chunk 到 VectorCandidate

MOMO Scholar 的向量检索分成两个通用阶段。

### Indexing / Ingestion 阶段

```text
多个 Chunk
→ 提取 Chunk Text
→ Embedder 批量生成 Chunk Embeddings
→ 校验数量、类型和维度
→ 初始化 Vector Store Collection
→ Upsert Chunk、Vector 和 Metadata
```

项目入口：

```python
retriever.index_chunks(chunks)
```

### Query / Retrieval 阶段

```text
User Question
→ Embedder 生成 Query Embedding
→ Vector Store 计算相似度
→ 按 Score 降序排列
→ 截取 Top-K
→ 返回 VectorCandidate
```

项目入口：

```python
retriever.retrieve(question, limit)
```

完整数据关系：

```text
Chunk
→ Chunk Embedding
→ Vector Record

Question
→ Query Embedding
→ Similarity Search
→ VectorCandidate
→ Fusion / Deduplication / Rerank
→ Evidence
```

需要保留边界：

> `VectorCandidate` 是向量召回候选，不是最终 Evidence。后续仍可与词法结果融合、去重并进行 Rerank。

## 九、为什么必须校验 Embedding 返回值

外部 Embedding 服务可能返回异常数据：

- 输入 3 段文本，只返回 2 个向量；
- 某个向量为空；
- 同一批向量维度不同；
- 返回字符串或布尔值而不是数字；
- 返回 `NaN` 或无穷大；
- 数值无法安全转换为浮点数。

项目中的 `_validate_embedding_batch()` 在外部服务边界检查这些问题，避免错误向量进入存储后造成：

- Chunk 与向量错位；
- 相似度结果错误；
- 数据库拒绝写入；
- 检索结果静默失真；
- 问题直到报告生成时才暴露。

这是“在边界尽早失败”的工程原则。

## 十、主体课程小结

1. Embedding 把文本转换为可计算的语义向量。
2. 单个向量维度通常没有明确、独立的人类含义。
3. 向量检索通过比较 Query Vector 和 Chunk Vector 寻找候选内容。
4. Cosine Similarity 主要比较向量方向。
5. Query 与 Chunk 必须使用兼容的同一 Embedding 模型。
6. VectorCandidate 还不是最终 Evidence。
7. 向量相似只代表语义接近，不代表内容一定支持 Claim。

## 十一、掌握检查

关闭文档后，尝试回答：

1. Embedding Model 和 Vector Store 分别负责什么？
2. Embedding 与关键词统计有什么区别？
3. 为什么单个向量维度通常不能直接解释？
4. 为什么不能用模型 A 索引 Chunk，再用模型 B 生成 Query Embedding？
5. 余弦相似度为什么要除以两个向量的长度？
6. 为什么 `score = 0.5` 不能直接解释为“中等相关”？
7. Indexing 和 Retrieval 分别执行哪些步骤？
8. VectorCandidate 与 Evidence 有什么区别？
9. 为什么要在外部服务边界校验 Embedding 返回值？

## 十二、关联学习记录

- `embedding-vector-retrieval-learning-log.md`：原始回答、理解纠正、点积、多行多列矩阵和通用术语映射。
- `../rag-glossary.md`：随课程持续追加的 RAG 中英文专业术语表。
