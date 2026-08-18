# 常见后端追问与诚实边界

## 架构与队列

### Q：现在到底有没有 Worker？

有一个**进程内 daemon worker thread**，类名是 `TechScoutSingleRunExecutor`；它不是独立服务，也不是 Redis/Celery Worker。当前一次最多执行一个 TechScout run。

### Q：为什么不用 Celery/Redis？

当前目标是本地单用户垂直切片，SQLite WAL 能用较低复杂度验证准入、状态、恢复和发布合同。Redis Worker 正在本轮主实现中推进，但尚未进入当前事实基线或完成验证；先定义 lease/fencing 不变量，再引入分布式运行时，避免只有队列没有正确 ownership。

### Q：SQLite claim 会不会并发重复？

在同一 registry 内，`BEGIN IMMEDIATE`、是否已有 running 的检查和 `WHERE status='queued'` 条件更新把 claim 放在一个事务里。可以说它覆盖本地并发，不能说覆盖多个独立数据库或任意多进程部署。

### Q：是否 exactly once？

不是。当前更接近有 checkpoint 的 at-least-once 恢复；文件产物和 SQLite 终态之间没有跨资源事务。未来计划用 fencing token 限制单 owner 提交，但仍不会宣称 exactly-once execution。

## 恢复与一致性

### Q：重启怎么恢复？

executor 启动时把活跃 TechScout run 重新入队。RunEngine 发现 stage workspace 后按 run ID 从 Harness SQLite checkpoint 恢复。测试覆盖了 planning checkpoint 后中断再恢复。

### Q：如果在写完产物、更新数据库前崩溃？

这是明确的当前窗口。现有顺序会保留产物/中断 Trace并重新入队，但没有自动 reconciliation。生产化计划是 attempt 隔离、manifest digest、fencing 条件提交和对账器。

### Q：checkpoint 会不会损坏？

stage workspace 有 tmp + fsync + replace 和一个 backup；Harness checkpoint 是 SQLite。仍不能保证所有磁盘故障都可恢复，故障注入计划包含主 workspace 损坏、磁盘满和 SQLite 锁场景。

### Q：如何避免无限重试？

Harness 的业务阶段恢复是类型化且有界的，当前 projection 里 attempts 最大为一次。Redis 层的 retry/backoff/DLQ 正在本轮实现中但尚未验证；实现合同要求总 attempt 上限和 full jitter。

## API 与错误

### Q：错误协议是什么？

当前 envelope 是 `error.code/message/details`。Pydantic 校验映射为 422；未知异常只返回 correlation ID。事件文本做脱敏和长度限制。

### Q：协议有什么已知问题？

`executor_unavailable` 在服务层被抛出，但基线固定 message 表没有对应项，可能降级为 internal error。我会把它当作待修合同缺口，而不是掩盖成稳定能力。

### Q：客户端什么时候可以重试？

当前只有部分路径有 `Retry-After`，v2 还未统一 retryable 合同。计划会为每个 code 登记 retryable 与有界等待时间；客户端不能对所有 500/503 无限重放 POST。

## Redis 与 lease（本轮实现中，不是基线已实现）

### Q：为什么 lease 还要 fencing token？

lease 只能说明 ownership 可能过期，不能让旧 Worker 忘记自己。网络分区或暂停后，旧 Worker 可能恢复并迟到写结果；递增 fencing token 让持久层拒绝旧 owner 的写入。

### Q：heartbeat 超时怎么办？

Worker 不能假设 lease 仍有效。本轮实现合同是在安全点停止新阶段，查询 owner/token；无法确认时 fail closed。外部调用 timeout 也必须小于 lease 安全窗口。当前基线尚未验证该行为。

### Q：Redis 挂了，任务会不会丢？

设计目标是不丢业务事实：Redis 只存调度态，run 投影、manifest、Trace 和产物在持久事实源。Redis 恢复后由 reconciliation 重建非终态调度项。这套机制正在本轮实现中，但当前基线尚未包含，也未完成演练。

### Q：为什么不把报告也放 Redis？

报告和 Trace 体积大、需要长期审计与摘要校验；Redis 更适合短期协调。把它作为唯一事实源会把队列故障扩大成业务数据丢失。

## 安全、运维与规模

### Q：现在能公网部署吗？

不应直接公网部署。当前默认 loopback、单用户、无认证；虽然有同源校验、CSP、请求大小限制和输出脱敏，但没有多租户授权。

### Q：有生产 SLO 吗？

没有。仓库有确定性工程测试和规划目标，但没有生产流量、on-call 或 SLO 证据。我会先实现指标和故障注入，再用部署数据设阈值。

### Q：扩容瓶颈在哪里？

最直接的是单 TechScout worker thread、SQLite 单写协调，以及本地产物/checkpoint。扩容前需要共享持久存储、Redis lease/fencing、幂等准入和对账，而不只是把 Uvicorn worker 数调大。

### Q：三个 STAR 是真实事故吗？

不是。它们是确定性故障注入/恢复测试：进程中断、PoC 首次失败、外部能力缺失。它们证明工程合同在受控条件下成立，不提供生产事故影响、MTTR 或真实模型效果。

## 一张诚实边界表

| 可以说 | 不能说 |
|---|---|
| “SQLite 事务化准入和 claim 已实现” | “已经是分布式队列” |
| “checkpoint 中断恢复有确定性测试” | “任务 exactly once” |
| “sealed Trace 与 limitation 可见” | “有完整生产 observability/SLO” |
| “Redis lease/fencing 正在本轮实现，当前基线未验证” | “Redis Worker 已上线” |
| “Fast Demo 走真实 orchestration seam” | “Fast Demo 是 live 或证明模型效果” |
| “故障案例来自注入测试” | “这是线上事故复盘” |
