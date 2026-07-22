# 向量索引工程链路学习记录

## 本轮学习目标

结合通用 RAG 术语和 MOMO Scholar 的真实代码，理解一批 Chunk 如何安全地转换为向量记录并写入 Vector Store。

本记录聚焦索引写入链路，不提前展开查询、混合检索和 Rerank。

## 一、四个核心概念

### Chunk

Chunk 是原始文档经过解析和切分后形成的检索文本单元。它不只有文本，还会保留来源信息：

```text
text        实际文本
chunk_id    文本块的稳定身份
paper_id    来源论文
section     来源章节
page        来源页码
token_count 文本长度
```

相比把整篇论文作为一个检索单元，Chunk 能让系统更精确地定位相关内容，也能减少交给生成模型的无关上下文。

### Embedding

Embedding Model 把 Chunk 文本转换成数字向量：

```text
Chunk Text
→ Embedding Model
→ [0.12, -0.35, 0.81, ...]
```

Embedding 既可以指文本转向量的过程，也可以指最终生成的向量。

### Vector Record

Vector Record 是 Vector Store 中的一条完整记录，类似数据库中的一行：

```text
chunk_id
paper_id
原始文本
embedding
section / page
content_hash
embedding_model
```

Vector Record 不是存储系统本身。

### Vector Store

Vector Store 保存和检索许多 Vector Record，并提供写入、过滤和相似度搜索能力。

四者关系：

```text
Paper
→ 解析和切分
→ Chunk
→ Embedding Model
→ Embedding
→ 与文本和 metadata 组成 Vector Record
→ 写入 Vector Store
```

## 二、通用索引链路

MOMO Scholar 的 `VectorRetriever.index_chunks()` 对应通用 RAG 的 Indexing / Ingestion 阶段：

```text
Chunks
→ 处理空输入
→ 检查 Embedding 模型身份
→ 提取文本
→ 批量生成 Embedding
→ 校验返回向量
→ 推断 vector_size
→ ensure_collection()
→ upsert()
```

它的主要职责是编排流程，而不是实现具体模型调用或数据库算法。

## 三、空输入为什么直接返回

```python
if not chunks:
    return
```

空列表表示当前没有文本需要建立索引。直接返回能够：

- 避免没有意义的外部模型调用；
- 避免额外延迟和费用；
- 避免供应商不接受空数组；
- 让空批次成为合法的 no-op。

其语义是：

```text
没有需要索引的数据
→ 什么都不做
→ 不属于错误
```

## 四、为什么模型不同不能比较

不同 Embedding 模型可能建立不同的语义坐标系。

```text
维度相同
→ 数学上可以计算

模型空间兼容
→ 计算结果才具有可靠语义
```

因此，即使两个模型都输出 768 维向量，也不能说明它们可以直接比较。

MOMO Scholar 在调用外部模型前检查：

```python
if self._embedder.model_name != self._store.embedding_model:
    raise ValueError(...)
```

这样可以尽早失败，避免浪费模型调用，并防止错误数据写入 Vector Store。

面试表达：

> Embedding 维度相同只代表向量在数学上可以计算，不代表它们属于同一语义空间。索引阶段的 Chunk 和查询阶段的 Query 必须使用兼容的同一 Embedding 模型。

## 五、批量 Embedding 与位置映射

批量调用：

```text
[text_A, text_B, text_C]
→ Embedder
→ [vector_A, vector_B, vector_C]
```

相比逐条调用，批量 Embedding 可以减少网络请求次数和协议开销，提高模型吞吐量。

当前接口依靠位置建立对应关系：

```text
texts[0] ↔ vectors[0]
texts[1] ↔ vectors[1]
texts[2] ↔ vectors[2]
```

如果输入三个文本却只返回两个向量，位置关系不再可信。系统不能猜测缺少的是哪一个，否则可能让 Chunk 绑定其他文本的向量，形成静默索引错误。

因此当前项目拒绝整个异常批次，不允许先写入部分结果。

生产系统若要支持逐项部分成功，返回协议需要携带稳定输入 ID 或索引以及每项状态，不能只依靠列表位置猜测。

## 六、Embedding 返回值校验

即使输入输出数量相同，向量仍可能不合法：

- 向量为空；
- 同一批向量维度不同；
- 包含字符串等非数字；
- 包含 Python 中可被视作整数的 `bool`；
- 包含 `NaN`；
- 包含正负无穷大；
- 向量无法安全转换为浮点数；
- 向量是零向量。

通用校验顺序：

```text
输入文本数 = 返回向量数？
→ 每个向量非空？
→ 批内维度一致？
→ 每个元素是数字且不是 bool？
→ 每个值可以转换为 float？
→ 每个数值都是有限数？
→ 符合 Collection 维度？
→ 不是零向量？
→ 才允许写入
```

这体现了“在外部服务边界尽早失败”的原则：错误向量不能进入内部存储后再等待检索阶段暴露。

## 七、向量长度与零向量

向量的 L2 范数为：

```text
||A|| = √(a₁² + a₂² + ... + aₙ²)
```

例如：

```text
A = [2, 1, 2]
||A|| = √(4 + 1 + 4) = 3
```

零向量的所有维度都是零：

```text
[0, 0, 0]
||A|| = 0
```

余弦相似度需要除以两个向量长度的乘积。任意一方为零向量时，分母为零，因此余弦相似度没有定义。

## 八、Collection 与固定 Schema

向量 Collection 是一组遵循相同规则、能够互相比较的 Vector Record。不同产品也可能称其为 table、index 或 namespace。

向量 Collection 通常需要确定：

```text
向量维度
Embedding 模型
距离函数
metadata Schema
索引配置
```

同一 Collection 通常要求：

```text
相同维度
+ 兼容的 Embedding 模型
+ 一致的距离定义
```

`ensure_collection()` 的通用含义是：

```text
Collection 不存在 → 创建
Collection 已存在且兼容 → 复用
Collection 已存在但冲突 → 拒绝或创建新版本
```

模型或维度升级时，通常需要创建新版本 Collection，重新生成 Embedding，验证后再切换查询流量，不能把新旧向量空间混合。

## 九、Upsert 是什么

`Upsert` 来自：

```text
Update + Insert = Upsert
```

含义是：

```text
记录不存在 → 新增
记录已存在 → 更新或覆盖
```

判断记录是否存在通常依靠唯一 ID。对于向量记录，这个 ID 可以是稳定的 `chunk_id`。

MOMO Scholar 的内存实现使用字典：

```python
self._records[chunk_id] = record
```

字典中 key 不存在时新增，key 已存在时覆盖，因此具备简单的 Upsert 语义。

## 十、稳定 chunk_id

稳定 `chunk_id` 负责让系统认出：

> 本次处理的 Chunk 与上一次处理的是同一个对象。

稳定 ID：

```text
第一次：chunk-001
第二次：chunk-001
→ Upsert 更新原记录
```

随机 ID：

```text
第一次：random-123
第二次：random-456
→ Vector Store 认为是两条记录
→ 产生重复数据
```

因此 Upsert 不会自动理解两段文本内容相同。它需要稳定身份作为判断依据。

如果论文内容或切分规则发生变化，Chunk 边界也可能变化。这时可以按 `paper_id` 删除旧 Chunk，再根据新版本切分并建立索引。

## 十一、幂等索引

幂等表示：

> 同一个操作执行一次或重复执行多次，最终系统状态相同。

幂等索引示例：

```text
第一次执行后：
[chunk-001, chunk-002, chunk-003]

相同任务再次执行后：
[chunk-001, chunk-002, chunk-003]
```

重复运行没有产生六条记录。

实现关系：

```text
稳定 chunk_id
→ 认出这是同一个 Chunk

Upsert
→ 已存在就覆盖，不存在就新增

最终
→ 重复执行不会产生重复记录
→ 实现幂等索引
```

只有 Upsert 而没有稳定 ID，仍会产生重复；只有稳定 ID 而只允许 Insert，重试时可能产生主键冲突。

## 十二、为什么幂等对重试重要

网络请求可能出现：

```text
服务端已经写入成功
→ 客户端等待响应时超时
→ 客户端不知道是否成功
→ 只能重试
```

如果索引操作幂等，重试会覆盖同一记录，最终状态仍然正确；如果不幂等，重试可能产生重复数据。

生产系统通常结合：

- 稳定 ID；
- Upsert；
- 批次内事务；
- 批次进度记录；
- 失败批次重试；
- 断点恢复。

## 十三、当前掌握结论

1. Chunk 是文档切分后的检索文本单元。
2. Embedding 是模型为文本生成的数字向量。
3. Vector Record 是包含文本、向量和来源信息的一条记录。
4. Vector Store 保存并检索许多 Vector Record。
5. 相同维度不代表属于相同语义空间。
6. 批量 Embedding 依赖输入输出的位置对应关系。
7. 外部向量必须在写入前完成结构、数值和维度校验。
8. 零向量长度为零，不能用于余弦相似度。
9. Collection 是具有固定向量 Schema 的逻辑集合。
10. Upsert 表示记录不存在就新增，存在就更新。
11. 稳定 `chunk_id` 让系统识别同一个 Chunk。
12. 稳定 ID 与 Upsert 配合，使重复索引后的最终状态保持一致。

## 十四、下一步

继续学习索引链路的失败边界与批次原子性：

```text
为什么发现一个非法向量时拒绝整个批次？
为什么先构造 pending records，再统一写入？
生产数据库如何用事务、分批和断点恢复处理部分失败？
```
