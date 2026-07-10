# MOMO Scholar MVP Design

日期：2026-07-10  
状态：MVP 范围冻结，等待实现计划  
目标交付窗口：2026 年 7 月内完成可展示版本，2026 年 8 月用于简历投递

## 1. 项目定位

MOMO Scholar 是一个面向简历展示的论文研读与综述助手。第一版不追求“大而全的科研平台”，而是聚焦一个可讲深、可运行、可展示的核心闭环：

```text
research question
  -> paper retrieval
  -> PDF / abstract parsing
  -> evidence extraction
  -> cross-paper synthesis
  -> citation-traceable report
  -> lightweight evaluation
```

项目卖点不是“总结论文”，而是：

- 能围绕研究问题检索候选论文。
- 能保留 paper、section、page、chunk 等证据来源。
- 能生成带引用、可追溯的 mini survey。
- 能输出 `papers.json`、`evidence.json`、`report.md`、`eval_report.md` 等工程化产物。
- 能用轻量评测说明 retrieval quality、citation support rate 和 unsupported claim rate。

## 2. MVP 范围冻结

### 2.1 必做能力

| 能力 | MVP 做法 | 说明 |
|:---|:---|:---|
| CLI 入口 | `momo-scholar run "<research question>"` | 第一版 CLI-first，降低 UI 成本 |
| 论文检索 | arXiv API 优先，Semantic Scholar / OpenAlex 作为元数据补全 | 先保证能稳定拿到 5-10 篇候选论文 |
| 元数据规范化 | 统一 title、authors、year、abstract、url、pdf_url、source | 为后续去重、排序、展示做基础 |
| PDF / 文本读取 | 优先公开 PDF；失败时退回 abstract | 不让 PDF 下载失败阻断完整流程 |
| chunk 与证据 | 按 section/page 或固定 token 窗口切分 | 每个 evidence span 必须可追溯 |
| 单篇结构化阅读 | contribution、method、experiment、limitation | 使用 Pydantic schema 约束输出 |
| 多篇综合 | 生成对比表和 mini survey | 重点展示方法谱系和差异 |
| 引用追踪 | claim 绑定 evidence id | 防止报告变成无来源生成文本 |
| 评测报告 | 小型固定 eval set | 输出 retrieval、citation、faithfulness 相关指标 |
| 极简展示页 | 从输出目录渲染 HTML | 只做展示，不做复杂交互 |

### 2.2 暂不做

- 不训练模型。
- 不搭完整 Web App。
- 不做复杂多 Agent 协作编排。
- 不做大规模本地论文库。
- 不做完整 LitQA / ScholarQABench 复刻。
- 不做自动科研实验、代码执行和论文生成。
- 不做 Paper2Agent 风格的 MCP server 生成，但保留工具化模块边界。

### 2.3 后续增强

- reranker。
- citation graph expansion。
- query expansion。
- hallucination checker。
- 更完整的 benchmark。
- MCP server。
- Web dashboard。

## 3. 参考项目取舍

| 项目 | 借鉴点 | 不照搬点 |
|:---|:---|:---|
| GPT Researcher | planner、researcher、publisher 的 report pipeline | 不做通用网页深度调研平台 |
| STORM | outline-first 长报告生成 | 不做百科式通用知识写作 |
| OpenScholar | scientific RAG、reranking、citation attribution | 不做大规模 datastore 和模型训练 |
| PaperQA | full-text retrieval、source relevance、LitQA 风格评测 | 不追求完整科学 QA benchmark |
| Paper2Agent | 工具化产物、reports、tests、benchmark、quality report | 不把论文代码库转 MCP agent |
| The AI Scientist | 自动科研流程的边界、成本和风险意识 | 不做自动实验和论文生成 |

## 4. 用户流程

第一版主流程：

```bash
momo-scholar run "LLM agents for scientific literature review"
```

系统创建一次 run：

```text
outputs/<run-id>/
  papers.json
  evidence.json
  report.md
  report.html
  eval_report.md
  logs.jsonl
```

用户可以打开 `report.html` 展示，也可以直接阅读 `report.md`。

## 5. 系统架构

```text
Research Question
  -> Query Planner
  -> Paper Retriever
  -> Metadata Normalizer
  -> PDF/Text Loader
  -> Chunker
  -> Evidence Retriever
  -> Paper Reader
  -> Survey Synthesizer
  -> Citation Checker
  -> Report Renderer
  -> Evaluator
```

### 5.1 模块边界

| 模块 | 输入 | 输出 | 责任 |
|:---|:---|:---|:---|
| Query Planner | research question | search queries | 拆解检索意图，生成 2-4 个 query |
| Paper Retriever | search queries | raw paper records | 调用 arXiv / Semantic Scholar / OpenAlex |
| Metadata Normalizer | raw records | `Paper` objects | 去重、排序、字段标准化 |
| PDF/Text Loader | `Paper` objects | raw text / abstract text | 下载公开 PDF 或回退 abstract |
| Chunker | paper text | `Chunk` objects | 保留 paper、section、page、offset |
| Evidence Retriever | question + chunks | `Evidence` objects | 找与研究问题最相关的证据片段 |
| Paper Reader | paper + evidence | `PaperAnalysis` | 抽取贡献、方法、实验、局限 |
| Survey Synthesizer | analyses + evidence | `ReportDraft` | 生成综述、对比表、开放问题 |
| Citation Checker | report + evidence | checked claims | 标记 unsupported / weakly supported claim |
| Report Renderer | checked report | markdown / html | 输出可展示报告 |
| Evaluator | outputs + eval cases | `eval_report.md` | 统计检索、引用、生成质量 |

## 6. 核心数据结构

### 6.1 Paper

```json
{
  "paper_id": "arxiv:2401.00001",
  "title": "...",
  "authors": ["..."],
  "year": 2024,
  "abstract": "...",
  "url": "...",
  "pdf_url": "...",
  "source": "arxiv",
  "citation_count": 123
}
```

### 6.2 Chunk

```json
{
  "chunk_id": "paper_id:chunk:001",
  "paper_id": "arxiv:2401.00001",
  "section": "Method",
  "page": 4,
  "text": "...",
  "token_count": 320
}
```

### 6.3 Evidence

```json
{
  "evidence_id": "ev_001",
  "paper_id": "arxiv:2401.00001",
  "chunk_id": "paper_id:chunk:001",
  "claim_type": "method",
  "quote": "...",
  "relevance_score": 0.86
}
```

### 6.4 Report Claim

```json
{
  "claim": "Recent paper-reading agents increasingly combine retrieval with post-hoc citation attribution.",
  "evidence_ids": ["ev_001", "ev_014"],
  "support_status": "supported"
}
```

## 7. 输出报告结构

`report.md` 默认结构：

```md
# Mini Survey: <research question>

## TL;DR

## Selected Papers

## Method Taxonomy

## Cross-paper Comparison

## Key Claims with Evidence

## Limitations and Open Questions

## References
```

每条关键结论都应该包含 evidence 标记，例如：

```md
Retrieval-augmented scientific agents rely on explicit source grounding to reduce hallucination. [E1, E7]
```

`report.html` 只负责把同样内容做成可展示页面：

- 左侧：论文列表和指标。
- 主体：综述正文。
- 右侧或折叠区域：evidence trace。
- 底部：eval summary。

## 8. 评测设计

### 8.1 MVP 评测集

第一版准备 10-20 条固定 case，覆盖：

- 主题检索：是否找到相关代表论文。
- 单篇理解：结构化提取是否与论文内容一致。
- 多篇对比：方法维度是否公平、是否混淆论文。
- 引用支撑：关键 claim 是否能追溯到 evidence。

### 8.2 指标

| 指标 | 含义 | MVP 计算方式 |
|:---|:---|:---|
| retrieval_hit_rate | 检索结果是否命中人工期望论文或关键词 | 人工 gold list / keyword match |
| evidence_coverage | 报告关键段落是否有 evidence | 有 evidence 的 claim 数 / 总 claim 数 |
| unsupported_claim_rate | 无证据支撑的 claim 比例 | unsupported claim 数 / 总 claim 数 |
| citation_validity | citation 是否指向真实 paper / chunk | 抽样人工检查 |
| run_cost | 单次运行成本 | 记录模型调用 token 和费用估计 |

## 9. 错误处理和降级策略

- arXiv 无结果：改写 query 后重试一次。
- PDF 下载失败：使用 abstract-only 模式继续流程。
- PDF 解析失败：记录到 `logs.jsonl`，该论文降级为 metadata + abstract。
- 模型 JSON 输出失败：重试并要求修复为 schema。
- evidence 不足：报告中明确标注 `insufficient evidence`，不强行生成结论。
- API rate limit：缓存已有结果，提示稍后重试。

## 10. 技术选择

| 层 | MVP 选择 | 原因 |
|:---|:---|:---|
| 语言 | Python | 学术检索、PDF、RAG 生态成熟 |
| CLI | Typer 或 Click | 快速做出可用命令行 |
| Schema | Pydantic | 约束 LLM 结构化输出 |
| PDF | PyMuPDF 优先 | 简单、快、足够 MVP |
| 存储 | JSONL + SQLite 可选 | 先轻量，后续可扩展 |
| 向量索引 | 先内存 / FAISS / Chroma 三选一 | MVP 可从简单检索开始 |
| 模型 | OpenAI-compatible API 优先 | 8 月前降低本地模型适配风险 |
| 展示页 | 静态 HTML | 不引入复杂前端框架 |
| 测试 | pytest | 验证工具函数、schema 和 pipeline |

## 11. 里程碑

### Milestone 1：Vertical Slice

目标：跑通 research question -> paper list -> mini review。

交付：

- CLI 命令。
- arXiv 检索。
- `papers.json`。
- `report.md`。

### Milestone 2：Evidence Trace

目标：让报告关键 claim 可追溯。

交付：

- PDF / abstract loader。
- chunker。
- `evidence.json`。
- claim -> evidence 映射。

### Milestone 3：Cross-paper Survey

目标：从单篇总结升级到多篇对比。

交付：

- `PaperAnalysis` schema。
- 方法对比表。
- limitation / open question。
- citation checker 初版。

### Milestone 4：Eval and Showcase

目标：变成可投简历的项目。

交付：

- 10-20 条 eval cases。
- `eval_report.md`。
- `report.html`。
- README demo。
- 架构图和简历 bullet。

## 12. 简历展示目标

简历描述方向：

> Built a CLI-first Scholar Research agent that retrieves scientific papers, parses PDFs, extracts evidence-grounded claims, and generates citation-traceable literature reviews with lightweight evaluation for retrieval quality and citation faithfulness.

可展示亮点：

- 可运行 CLI demo。
- 可打开 HTML 报告。
- 可展示 evidence trace。
- 可展示 eval report。
- 可讲清楚模块边界和失败降级。

## 13. 风险与控制

| 风险 | 控制策略 |
|:---|:---|
| 范围膨胀 | 7 月只做 CLI-first + report + eval |
| PDF 解析不稳定 | abstract fallback |
| 生成幻觉 | claim 必须绑定 evidence |
| API 不稳定 | cache + graceful fallback |
| UI 消耗时间 | 静态 HTML，不做完整 Web App |
| 评测太重 | 先做 10-20 条小型 eval |

## 14. 当前决策

- 项目目标：简历项目，要求有一定技术深度。
- 交付时间：2026 年 7 月内完成第一版，2026 年 8 月用于投简历。
- 产品形态：CLI-first，最后补极简展示页。
- 技术深度重点：evidence-grounded generation、citation trace、lightweight eval。
- 实现策略：先 vertical slice，再逐层加 evidence、comparison、eval、showcase。

## 15. 待确认事项

实现计划前需要确认：

1. 第一版模型供应商：OpenAI / OpenAI-compatible API / 其他云模型。
2. 是否按 milestone 使用分支和 commit 节奏推进。

