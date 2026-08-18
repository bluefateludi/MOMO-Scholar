# 故障注入计划

> 状态：**本轮计划**。本文定义未来验证，不声称这些场景已在生产环境演练。当前仓库已有部分确定性测试，单独列出。

## 1. 原则

- 默认在隔离环境、fake adapter 或受控容器内注入，不触碰真实第三方服务。
- 每次实验固定 seed、输入与预期不变量，保留失败前后的 Trace、checkpoint、事件和产物摘要。
- 验证的是可靠性机制，不记录或推断真实模型效果。
- 先验证单故障，再组合故障；设置总时限和停止条件，避免无限重试。
- 注入工具不得包含 secret，不得对生产数据执行破坏性操作。

## 2. 已实现的确定性覆盖

| 场景 | 已有证据 | 当前验证点 |
|---|---|---|
| 并发准入超过容量 | `tests/web/test_registry.py` | 事务化容量检查，只接受有界数量，其余 `queue_full` |
| 终态发布异常后的队列释放 | `tests/web/test_registry.py` | stuck running 可兜底转为 failed，不永久阻塞下一任务 |
| Web 刷新/重启后的 checkpoint 恢复 | `tests/web/test_techscout_wave2_e2e.py` | 活跃 run 重排，Harness 从 checkpoint/workspace 继续 |
| PoC 首次失败后单阶段恢复 | Wave 2 E2E / recovery tests | 有界恢复、失败历史与 recovery Trace 可见 |
| live/cache/Docker 缺失的受限结果 | verified integration tests | 显式 limitation/no-safe-winner，而非伪造成功 |

这些是测试或故障注入案例，不是线上事故和生产 SLO 证据。

## 3. 本轮计划：基线单进程矩阵

| ID | 注入点 | 注入方式 | 期望不变量 |
|---|---|---|---|
| L1 | claim 后、首个 checkpoint 前杀进程 | 子进程硬退出 | 重启后 run 可重排；不出现两个本地 running owner |
| L2 | checkpoint 后、产物发布前杀进程 | stage hook | 从最近 checkpoint 恢复；已完成阶段不被无限重复 |
| L3 | 产物已写、Trace seal 前杀进程 | file hook | 旧 Trace 以 interrupted/aborted 形式保留；新 Trace 可验证 |
| L4 | Trace seal 后、registry 终态前杀进程 | commit hook | 重启后不把不一致 run 静默当成功；对账需求被暴露 |
| L5 | SQLite `database is locked` | fake connection/受控锁 | 失败有界、无 busy loop；API 不泄露 SQL/路径 |
| L6 | 输出卷只读/磁盘满 | 隔离临时卷 | 进入安全 failed 或明确不可用；不生成半真半假的成功投影 |
| L7 | stage workspace 主文件损坏 | 改坏临时 fixture | 能读 backup 或明确失败；不忽略校验错误 |
| L8 | 终态发布连续失败 | fake publisher | `fail_stuck_techscout` 尽力释放队列，故障日志可关联 |

## 4. 本轮计划：Redis/Worker 矩阵

在 Redis 协议实现后才能运行：

| ID | 注入点 | 期望不变量 |
|---|---|---|
| R1 | Worker claim 后崩溃 | lease 到期后仅一个新 token 被 claim；旧 token 无权提交 |
| R2 | Worker 暂停超过 TTL 后恢复 | fencing 拒绝旧 Worker 的 heartbeat/progress/complete |
| R3 | heartbeat 请求超时但 Redis 已成功执行 | Worker 先查 ownership；不盲目扩 lease 或重复副作用 |
| R4 | Redis 在 claim Lua 前后故障 | claim 要么完全发生、要么完全不发生，无半状态 |
| R5 | complete 返回超时 | 使用 run/token 查询幂等判断，不创建重复终态事件 |
| R6 | reaper 与 heartbeat 竞争 | 原子条件保证只有 expiry/owner/token 匹配才回收 |
| R7 | 可重试依赖错误连续发生 | 有界退避，超预算进入 DLQ，不无限重试 |
| R8 | Redis 数据丢失/重启 | 从持久 run store 重建非终态项；终态产物不由 Redis 丢失 |
| R9 | 两个 API 使用同一 idempotency key | 相同 digest 返回同一 run；不同 digest 返回冲突 |
| R10 | DLQ 重放 | 保留原失败，生成新 attempt/token，可审计且不会覆盖旧证据 |

## 5. 通过标准

每个场景必须自动断言：

- run 状态与事件序列合法，没有从终态回到 running。
- 同一时刻最多一个有效 fencing token。
- 尝试次数、恢复次数和 lease loss 可从结构化事件还原。
- 终态引用的 manifest/产物摘要可验证；失败时不发布推荐性结果。
- 日志、错误响应、事件和 Trace 不含 canary secret。
- 测试在硬时限内终止，不依赖真实网络或真实模型效果。

## 6. 未实现的交付物

- fault hooks/代理、Redis 测试容器与虚拟时钟。
- chaos 场景自动化、CI 隔离 job 和产物归档格式。
- 对 L4 跨存储窗口的 reconciliation 实现与合同测试。
- 生产演练审批、回滚方案、观察窗口和 SLO 阈值。
