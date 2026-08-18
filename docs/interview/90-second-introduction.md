# 90 秒项目介绍

## 可直接使用的版本

“MOMO TechScout 是一个帮助 Python AI 应用开发者选择开源组件的证据驱动研究与验证 Agent。用户给出环境、硬约束和候选组件后，系统会经过有界的规划、检索、PoC 验证和确定性 gate，输出可追溯的对比报告，而不是让模型在开放循环里自由决定是否发布结论。

我这部分重点解决的是本地 Web 后端的可靠执行。**已经实现的部分**是 FastAPI API、SQLite WAL 运行注册表、append-only 事件、单 TechScout 后台线程、Harness checkpoint、阶段 workspace、失败投影和封存 Trace。任务从 queued 到 running 的 claim 使用事务和条件更新；进程重启后活跃任务会重新入队，如果已有 checkpoint，就从最近阶段恢复。终态前先持久化产物并 seal Trace，再把 projection path、终态和终态事件放在同一个 SQLite 事务里。系统还会把缺少 live provider 或 Docker 等情况显式降级，不把缺失基础设施解释成候选组件不兼容。

我会明确它目前还是**单进程、本地、无认证**的垂直切片，Fast Demo 也是 synthetic。**本轮实现中**的工作是把 API 与执行解耦成 Redis 队列和独立 Worker，增加 lease、heartbeat、fencing token、有界重试和 DLQ；协议已经写清，但这些能力尚未进入当前事实基线，也尚未完成验证。因此我不会宣称它已经多实例上线，也不会用 synthetic 运行谈真实模型效果。”

## 30 秒压缩版

“TechScout 是一个有界的开源组件研究与验证 Agent。我实现了本地可靠执行切片：FastAPI + SQLite WAL 队列投影、单 Worker thread、checkpoint 恢复、失败安全发布和 sealed Trace。它能把外部依赖缺失显示为 limitation，而不是伪造成功。当前边界是单进程、无认证、Fast Demo synthetic；Redis Worker、lease 与 fencing 正在本轮实现，但尚未进入当前基线或完成验证。”

## 状态提示

| 表达 | 状态 |
|---|---|
| SQLite WAL、事务 claim、单线程 executor、checkpoint/Trace | 已实现 |
| Redis Worker、lease、heartbeat、fencing、DLQ | 本轮实现中（当前基线未包含、未验证） |
| 多实例生产部署、SLO、真实流量事故经验 | 未实现 |
| 真实模型成功率/成本改善 | 不在本材料范围，不能推断 |
