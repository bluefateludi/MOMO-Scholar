# Redis Worker 与 lease 协议

> 状态：**本轮计划（仅协议文档）**。基线没有 Redis 依赖、独立 Worker、lease、heartbeat、fencing token、reaper 或 DLQ。

## 1. 设计目标

- 多 Worker 下同一时刻只有一个有效 owner 能推进任务。
- Worker 崩溃后任务可被回收，不永久卡在 running。
- 网络暂停或 GC pause 后的旧 Worker 不能覆盖新 owner 的结果。
- Redis 短暂不可用时停止获取新任务；不靠猜测继续续租或提交。
- 调度数据可重建，业务产物与最终事实不只存在 Redis。

## 2. 计划中的数据模型

以下 key 只是协议命名，尚未实现：

| Key | 类型 | 用途 |
|---|---|---|
| `ts:queue:ready` | sorted set | score 为可执行时间，member 为 run ID |
| `ts:queue:leased` | sorted set | score 为 lease expiry，供 reaper 扫描 |
| `ts:run:{id}` | hash | 调度态、owner、token、attempt、request digest |
| `ts:idempotency:{scope}:{key}` | string/hash | 映射 request digest 与 run ID，带保留期 |
| `ts:events` | stream | 调度事件；不是业务 Trace 的唯一权威 |
| `ts:queue:dead` | stream | 超预算任务与最后一次归一化错误 |
| `ts:fence:{id}` | counter | 单调递增 fencing token |

请求正文、凭证、完整错误文本和大产物不得放入 Redis。hash 只存引用、摘要和有界元数据。

## 3. 原子命令合同

所有多 key 状态变化通过 Lua script 或 Redis Functions 原子执行；Worker 不以多条独立命令拼接 claim。

### `admit(run_id, digest, idempotency_key, ready_at)`

1. 检查 idempotency 映射。
2. 相同 digest 返回既有 run；不同 digest 返回冲突。
3. 新 run 写 `ready` 状态并加入 ready zset。
4. 发出 `task.admitted` 调度事件。

### `claim(worker_id, now, lease_ttl)`

1. 从 ready zset 取 `score <= now` 的最早任务。
2. 递增 `ts:fence:{id}` 得到 token。
3. 将 run 置为 `leased`，写 owner、token、lease expiry 和 attempt。
4. 从 ready 移除并加入 leased zset。
5. 返回 run ID、token、attempt 与请求引用。

### `heartbeat(run_id, worker_id, token, new_expiry)`

只有 owner、token 与 `leased` 状态全部匹配才续租。返回“不匹配”即视为 lease 已丢失；Worker 必须停止写进度和终态。

### `complete(run_id, worker_id, token, outcome_ref, manifest_digest)`

只有当前 token 可移除 leased、写 `succeeded` 并发出完成事件。`outcome_ref` 必须先在持久存储中可读且摘要校验通过。

### `fail(run_id, worker_id, token, error_code, retryable, next_at)`

- 可重试且未超预算：状态改为 `retry_wait`，加入 ready zset，score=`next_at`。
- 不可重试或超预算：状态改为 `dead_lettered`，写入 dead stream。
- 原始异常、secret 和无界第三方响应不得进入 Redis。

### `reap(now)`

扫描已过期 leased 任务；仅当 hash 中 expiry 仍匹配时清 owner 并重排。reaper 不删除产物，不复用旧 token。

## 4. lease 参数原则

具体秒数必须经故障注入和真实阶段耗时分布校准，本文不伪造生产参数。实现时遵守：

- `heartbeat_interval < lease_ttl / 3`，为一次抖动留出余量。
- 单次外部调用 timeout 必须小于剩余 lease 安全窗口；长阶段需要可中断点。
- 心跳失败不是立即宣告任务失败；但 Worker 在无法确认 ownership 时必须 fail closed。
- lease expiry 使用 Redis 服务端时间，避免依赖 Worker 本机时钟。
- 重试使用 full jitter、有上限退避和总 attempt 上限；不允许无限重试。

## 5. fencing 与副作用

token 必须贯穿所有可变写入：

- run progress/event projection 采用 `WHERE run_id=? AND fencing_token=?` 条件写。
- 产物先写到 attempt/token 隔离前缀；只有成功终态把该前缀提升为 run authority。
- 外部不可幂等副作用默认禁止；若未来引入，必须使用幂等键或事务 outbox。
- 旧 Worker 即使稍后恢复，也只能发现 token 失效并退出，不能“补写”结果。

这提供的是 at-least-once 执行 + fencing 后的单 owner 提交，不宣称 exactly-once 执行。

## 6. Redis 故障策略

- API 无法完成原子准入：返回可重试 503，不先创建幽灵任务。
- Worker 无法 claim：停止拉取，保持存活探针与就绪探针语义分离。
- Worker 无法 heartbeat：停止启动新阶段；在安全点中断并保留 checkpoint。
- complete 结果不确定：不得无 token 重试写入；先查询 owner/token/终态再幂等重放 complete。
- Redis 数据丢失：从持久 run store 重建非终态调度项；Redis 本身不作为唯一业务事实源。

## 7. 未实现与开放问题

- Redis Cluster/Sentinel 选择、持久化策略、TLS/ACL 与 secret 轮换。
- Lua/Function 脚本、客户端库与 schema 迁移。
- 公平性、优先级、每租户并发和背压算法。
- 持久 run store 与 Redis 的 outbox/reconciliation 实现。
- checkpoint/产物共享存储和 attempt 前缀提升机制。
