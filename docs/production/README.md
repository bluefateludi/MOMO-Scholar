# TechScout 后端可靠性文档

> 事实基线：`750b17a7a2bf3217793c70e4fc065f1728288743`
>
> 本目录只描述工程实现、演进协议与运维验证。面试表达位于 [`../interview/`](../interview/README.md)。

## 状态词汇

- **已实现**：基线代码路径中存在，并有代码或测试可核对。
- **本轮计划**：本文档定义的下一阶段实现合同；尚未进入生产代码。
- **未实现**：既不在基线代码中，也不应被表述为已上线能力。

本文中的“生产”表示面向生产化的设计与运维要求，不表示系统已经部署到生产环境。

## 阅读顺序

1. [后端可靠性架构](architecture.md)
2. [错误协议](error-protocol.md)
3. [任务生命周期](task-lifecycle.md)
4. [Redis Worker 与 lease 协议](redis-worker-lease.md)
5. [运维 Runbook](runbook.md)
6. [故障注入计划](fault-injection-plan.md)

## 基线结论

| 能力 | 状态 | 基线事实 |
|---|---|---|
| API、队列投影与事件 | 已实现 | FastAPI + SQLite WAL；run 状态与 append-only 事件持久化 |
| TechScout 执行 | 已实现 | 单进程内一个 daemon thread；一次最多执行一个 TechScout run |
| 重启恢复 | 已实现但有限 | 启动时重排活跃任务；存在 stage workspace 时从 SQLite checkpoint 恢复 |
| 终态发布 | 已实现但有限 | 先生成投影/产物并封存 Trace，再在 SQLite 事务写终态状态与事件 |
| Redis 分布式队列 | 未实现 | 无 Redis 依赖、Worker 进程、lease、heartbeat、fencing token 或 DLQ |
| 多实例与多租户 | 未实现 | Web 默认单 worker、loopback、无认证 |
| 真实模型效果 | 不在范围 | 本目录不记录或推断模型质量、成功率、成本改善等结论 |
