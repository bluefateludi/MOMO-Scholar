# 可靠性 Deep Dive

## 一句话主线

我把可靠性拆成四个可验证的边界：**准入不超卖、执行可恢复、发布不撒谎、失败可追踪**；然后主动说明当前单进程边界，以及下一步如何用 lease + fencing 扩到多 Worker。

## 1. 准入不超卖（已实现）

`RunRegistry` 在 `BEGIN IMMEDIATE` 事务里统计 `queued/running` 数量、插入 run、追加 accepted 事件。并发测试证明容量检查发生在同一写锁边界内。claim 同样使用事务和 `WHERE status='queued'` 条件更新；而且只要库里有一个 TechScout `running`，就不会 claim 第二个。

面试边界：这保证的是**单 SQLite registry 内的有界并发**，不是分布式锁，也不是高吞吐队列。

## 2. 执行可恢复（已实现但有限）

Web 启动时把活跃 TechScout run 重新置为 queued。引擎把 Harness checkpoint 放在独立 SQLite 文件，把阶段副产物放在 workspace；workspace 采用 tmp + fsync + replace，并保留 backup。再次执行时，如果 workspace 存在，就让 Harness 按 run ID 从 checkpoint 恢复。

面试边界：这是 checkpoint-based resume，不是 exactly-once。进程可能在“产物已写、registry 尚未终态”的窗口退出，当前靠重排和保留 interrupted Trace 暴露问题，还没有跨存储事务或自动对账器。

## 3. 发布不撒谎（已实现）

Harness 有确定性 gate 和有界恢复。外部搜索、缓存、Docker 或 recipe 不可用时，系统产生 limitation、`no_safe_winner` 或 failed，而不是把基础设施缺失推断为组件不兼容。Fast Demo 在 API 中标记 `synthetic=true`。

成功路径先生成投影/manifest 等产物，再记录 terminal Trace 并 seal，最后在 SQLite 同一事务写终态状态、projection path 和终态事件。异常路径尽量发布失败投影；终态发布本身失败时，还有最后的 queue-release 兜底。

面试边界：文件系统与 SQLite 不是同一事务，因此只能说“有意安排提交顺序并提供恢复证据”，不能说“原子 exactly-once 发布”。

## 4. 失败可追踪（已实现）

系统有两层可观测性：registry 中的游标分页事件用于 Web 进度，run 目录中的 sealed JSONL Trace 用于执行/provenance。事件文本写入前会做脱敏、控制字符清理和长度限制；未知 API 异常只返回 correlation ID。

面试边界：这不是完整生产 observability。当前没有 Prometheus SLO、集中日志平台、告警路由或跨服务 request ID。

## 5. 为什么需要 lease + fencing（本轮实现中，尚未验证）

单进程重启时，可以直接假设旧线程消失；多 Worker 下这个假设不成立。Worker 可能只是网络分区或长暂停，lease 到期后新 Worker 会接管，而旧 Worker 随后恢复。如果只有分布式锁/TTL，旧 Worker 仍可能迟到写终态。

所以计划协议同时使用：

- lease：让崩溃任务最终可回收；
- heartbeat：存活 Worker 延长 ownership；
- fencing token：每次 claim 单调递增，所有进度/终态写都验证 token；
- attempt 隔离产物：旧 attempt 不能覆盖当前 authority；
- 有界 retry + DLQ：基础设施错误不会无限重放。

准确表述是“计划实现 at-least-once execution + fenced single-owner commit”，不是 exactly-once execution。

## 6. 可能被追问的取舍

### 为什么当前用 SQLite？

目标是本地单用户垂直切片。SQLite WAL 提供了足够清晰的事务、低运维成本和确定性测试；先验证任务合同和恢复边界，比过早引入分布式组件更合适。

### 为什么 Redis 不能成为唯一事实源？

队列和 lease 是短期协调状态；报告、manifest、Trace 和最终 run 投影需要更稳定的持久化、审计与对账。Redis 丢失后应该能从持久事实源重建调度态。

### 最大的当前技术债是什么？

跨文件系统与 registry 的发布窗口，以及 executor unavailable 错误码映射不一致。前者需要 attempt/fencing + reconciliation/outbox 思路，后者需要统一 error registry 和合同测试。
