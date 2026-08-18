# 任务生命周期

## 1. 已实现的公开状态

TechScout API 当前公开：

```text
queued -> running -> completed
                  -> completed_with_limitations
                  -> failed
```

阶段投影为 `plan -> research -> verify -> decide -> terminal`。Harness 内部阶段更细，API 通过映射暴露较稳定的五阶段视图。

## 2. 已实现的转移与提交点

| 转移 | 谁执行 | 当前原子边界 |
|---|---|---|
| 请求 -> `queued` | API / registry | run 行与 accepted 事件同一 SQLite 事务 |
| `queued` -> `running` | 单线程 executor | 条件更新与 started 事件同一 SQLite 事务 |
| `running` 阶段推进 | RunEngine progress callback | stage/progress 与对应事件同一 SQLite 事务 |
| `running` -> 终态 | executor / registry | status、projection path、finished time 与终态事件同一 SQLite 事务 |
| 进程重启 -> `queued` | executor startup | 每个活跃 run 独立事务，附 recovery 事件 |

终态发布顺序是：Harness 完成 → 生成 Web 投影和终态产物 → 记录并 seal Trace → registry 提交终态。文件系统与 SQLite 之间没有跨资源事务，因此这是一种可恢复发布顺序，不是严格 exactly-once 提交。

## 3. 生命周期不变量

已实现或由当前 schema 强制的不变量：

- 只有 `completed`、`completed_with_limitations`、`failed` 可写入 TechScout 终态。
- 同一 SQLite registry 同时最多有一个 `running` TechScout run。
- claim 使用 `WHERE status='queued'` 条件更新，避免同库内重复 claim。
- 终态 run 有 `finished_at`；成功/受限终态应有可读取的 projection path。
- Trace cursor 是基于单调自增 event sequence 的不透明 token。

需要注意的限制：

- 当前没有客户端 idempotency key；重复 POST 会创建不同 run。
- 启动协调会重排所有 `queued/running` TechScout run，不校验 lease owner。
- 当前没有 `cancelled`、`retry_wait`、`dead_lettered` 等公开状态。
- 阶段进度不是 checkpoint 本身；真正恢复依据是 Harness checkpoint 与 stage workspace。

## 4. 本轮计划：保持 API 稳定的内部状态机

Redis 调度层计划使用独立内部状态，不直接扩大公开 API：

```text
ready -> leased -> succeeded
               -> retry_wait -> ready
               -> dead_lettered
               -> cancelled
leased --lease expired--> ready
```

映射建议：

| 内部调度态 | 公开 run 状态 |
|---|---|
| `ready`、`retry_wait` | `queued` |
| `leased` | `running` |
| `succeeded` | `completed` 或 `completed_with_limitations` |
| `dead_lettered` | `failed` |
| `cancelled` | 先作为 `failed` + `cancelled` issue；是否新增公开状态需单独 API 决策 |

计划不变量：

- 创建请求携带 idempotency key；同一调用方、同一 key、同一请求摘要返回同一 run，不同摘要冲突。
- 每次 claim 生成递增 fencing token；任何进度、续租、终态提交都必须匹配当前 owner 与 token。
- Worker 先持久化产物并校验 manifest，再以 token 条件提交终态；旧 Worker 的迟到提交被拒绝。
- retry 只对登记为可恢复的基础设施错误生效，采用有界指数退避和总尝试预算。
- 业务结论为 `no_safe_winner` 或 `completed_with_limitations` 时是正常终态，不进入基础设施重试。
- reaper 只回收过期 lease；它不直接宣称任务失败，也不删除 checkpoint 或产物。

## 5. 未实现与待决策

- 幂等准入、取消 API、公开 cancelled 状态。
- retry 分类表、最大尝试数、退避参数和 DLQ 运维流程的代码实现。
- 多 Worker 情况下 checkpoint 的共享存储与并发打开策略。
- “产物已持久化但终态提交失败”的 outbox/对账器。
- 任务保留周期、删除协议与合规要求。
