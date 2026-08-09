# 面试故事与四条中文 STAR 简历稿

本页只使用 [最终交付 authority](final-delivery.md) 中可核验的产品验收、测试和 CI 事实。Synthetic runner 的 Task Success、Recall、fault、token 与毫秒级诊断值不进入简历成果。

## 九十秒项目故事

MOMO Scholar 已有检索、Evidence、Trace、评测、API 和 Web 基础设施，但主流程仍是固定的论文流水线。我把它重构为面向 Python AI 开发者的开源组件调研与验证 Agent：输入环境、硬约束和候选组件后，系统通过有界 LangGraph Harness 规划研究，按阶段选择 Skill，经本地 MCP 边界调用工具，并由确定性 Gate 决定能否发布推荐。

核心取舍是把“模型判断”和“系统权限”分开。模型或确定性 stage service 可以规划、诊断和审阅；代码负责状态转换、预算、工具权限、受信 PoC recipe、Docker argv 编译、终态和发布门。Chroma 与 Qdrant Local 拥有受审 recipe，pgvector 和未知候选在缺少可信 fixture 时只能 research-only。失败恢复只重跑失败 stage，并保留 checkpoint 与原始 Trace。

交付时我没有把 synthetic 结果包装成真实效果：Fast Demo 使用真实 Harness、Skill、stdio MCP、checkpoint、Gate、artifact 和 sealed Trace，但 evidence/PoC 是冻结 synthetic 数据；Verified/Live 未接通时明确返回 limited。最终 Chromium 验收中，连续三次 Hero Fast Demo 都在预算内终态化，并覆盖 cache 降级、单次恢复、未知候选、刷新恢复、失败安全和窄屏路径。

## 高频追问

- **为什么不用自由 ReAct 循环？** 有界状态机、严格 schema、预算和确定性终态能把失败行为变成可测试契约，避免模型自行扩大权限。
- **为什么本地也使用 MCP？** 它验证了真实的 typed client/server 工具边界；Skill allowlist 与本地 policy 必须同时允许，MCP 元数据本身不承担授权。
- **为什么 research-only 不是“不兼容”？** 缺少可信 recipe 说明验证 authority 不足，不等于组件已被证明失败。
- **为什么拆分两个 SQLite？** 产品队列/事件与 LangGraph checkpoint 的所有权和生命周期不同，拆分后编排内部表不会变成产品事实来源。
- **如何证明没有夸大效果？** 浏览器验收、测试/CI 和 synthetic runner 诊断分别记录；PR #93 的 sealed final audit 将后者的 Task Success、Recall、Recovery、Token、latency 与 Cost resume authority 永久标为 N/A。

## STAR 1 — Agent 产品化与可解释交付

- **S（情境）：** 原项目拥有完整 RAG 与证据基础设施，但固定论文流水线不足以展示 Agent 的规划、工具选择和终态控制。
- **T（任务）：** 在保留可追溯资产的同时，交付一个面向 Python AI 组件选型的有界 Agent 产品。
- **A（行动）：** 设计严格请求/状态/报告契约，以 LangGraph 组织阶段化 Harness，引入 runtime Skills、本地 stdio MCP、独立 checkpoint、确定性 Validation Gate、不可变 artifact 与 sealed Trace。
- **R（结果）：** Chromium 中连续三次 Hero Fast Demo 均在 120 秒预算内终态化，wall-clock 分别为 45.081 s、15.360 s、12.879 s，且全程明确标注冻结 synthetic 边界。

简历一句话：**将固定 RAG 论文流水线重构为有界 LangGraph/MCP 组件调研 Agent，以 typed state、stage Skill、checkpoint 和确定性发布门形成可审计闭环；连续三次 Hero 浏览器验收均在 120 秒内终态化（45.081 s / 15.360 s / 12.879 s）。**

## STAR 2 — 安全 PoC 与诚实降级

- **S（情境）：** 让模型生成安装命令并直接操作宿主机会带来不可复现的供应链、网络、挂载和 secret 风险。
- **T（任务）：** 在允许局部组件验证的同时，阻止任意 shell 和未经审查的候选跨越执行边界。
- **A（行动）：** 建立 Chroma/Qdrant Local 闭集 recipe、结构化 PoC compiler、显式 Docker argv、资源/网络/输出限制和 fail-closed policy；pgvector 与未知候选自动降级为 research-only。
- **R（结果）：** PR #92 的 Python、Web、sandbox build/no-network smoke 三项 CI 均通过；未知候选浏览器路径未产生对应 `sandbox.run_smoke_test` 事件，并返回 `no safe winner`。

简历一句话：**构建 fail-closed Docker PoC 边界，以受审 recipe、显式 argv、资源/egress 限制和 research-only 降级阻止任意命令执行；PR #92 的 Python、Web、sandbox 三项 CI 全绿。**

## STAR 3 — 定向恢复与可观测性

- **S（情境）：** 搜索、依赖、PoC 或报告失败若重启整条 Agent 链路，会重复工作并掩盖失败根因。
- **T（任务）：** 让恢复有界、只重跑失败阶段，同时保留原始失败与恢复证据。
- **A（行动）：** 增加 typed failure classifier、checkpoint-linked recovery、预算终态化、append-only events 与 sanitized sealed Trace；恢复策略只允许映射到受控动作。
- **R（结果）：** 浏览器验收完成一次依赖冲突恢复：保留 checkpoint，执行 `pin_version_and_rerun_poc`，仅重复 `execute_poc`，终态显示 recovered，刷新后状态仍可恢复；不将该单路径验收包装为 Recovery Success 百分比。

简历一句话：**实现 checkpoint-linked 定向恢复与 sealed Trace，在依赖冲突验收中仅重跑失败的 `execute_poc` 阶段并持久化 recovered 状态，避免整链重启和不可审计重试。**

## STAR 4 — 质量门与证据分层

- **S（情境）：** 全仓测试、focused 回归、浏览器验收和 synthetic 评测诊断容易被混成一个“效果数字”。
- **T（任务）：** 建立可追溯的交付证据层级，让每个数字都带范围、commit 和适用边界。
- **A（行动）：** 分离 full-integration、PR focused、三项 CI、浏览器 acceptance 与 synthetic runner authority；永久保留四条限制：原始失败、单次数据修订且禁止再跑、延迟封存 preflight、以及 synthetic 行为导致产品/简历指标 N/A。
- **R（结果）：** 产品全量集成在 `b7516a7` authority 达到 1462 passed、3 skipped；最终 PR #92 在 `7c6a9ed` 完成 focused Python 118 passed、2 skipped与 Web 22 passed，并保持 Python、Web、sandbox 三项 CI 全绿。

简历一句话：**建立按 scope/commit 分层的质量门与交付证据：全量集成 1462 passed、3 skipped，PR #92 focused Python 118 passed、2 skipped及 Web 22 passed，Python/Web/sandbox 三项 CI 全绿，同时禁止 synthetic 诊断冒充产品效果。**

## 禁止表述

- 不把 Fast Demo 描述为 Live、真实 provider 或真实 Docker 执行。
- 不把已经实现但尚未 Web-wired 的 adapter/runner 描述为端到端能力。
- 不把 research-only 描述为兼容性失败。
- 不把 synthetic runner 的 `12/40/8`、Task Success、Recall、fault、token 或延迟写进简历成果。
- 不复用 MOMO Scholar 的检索、Citation 或旧 Browser 数字作为 TechScout 效果。
