# TechScout 运维 Runbook

## 1. 适用边界

本 Runbook 分两段：基线可执行的本地单进程操作，以及尚未实现的 Redis/Worker 目标操作。不要把后者当作当前命令手册。

## 2. 已实现：本地启动与健康核对

安装与启动见 [`../techscout/running.md`](../techscout/running.md)。默认：

```console
techscout serve
```

安全边界：默认 `127.0.0.1:8000`、Uvicorn 单 worker、无认证。除非已有外部网络保护，不要使用 `--allow-network` 暴露到非 loopback。

启动后最小检查：

1. `GET /api/v2/runs` 能返回列表，API 响应含 `Cache-Control: no-store`。
2. 提交一个明确的 Fast Demo 请求，确认状态从 `queued/running` 进入终态。
3. 核对 `outputs/.web/run-registry.sqlite3` 存在，且对应 run 的 `outputs/techscout/<run-id>/` 中有 projection、manifest 与 sealed Trace。
4. Fast Demo 的 synthetic 标识必须保持可见；不要将其描述为 live 或真实模型结果。

## 3. 已实现：常见故障处置

### A. `queue_full`

- 含义：SQLite 中 `queued/running` TechScout 数量达到配置容量；不代表 CPU 或 Redis 指标。
- 操作：查询 run 列表，识别长期非终态任务；先保存数据库、日志和 run 目录证据。
- 禁止：直接改 SQLite 状态、删除 run 目录或反复提交新任务掩盖问题。

### B. 任务长期 `running`

- 查看进程是否仍存活、磁盘是否可写、run 目录最近修改时间、`stage-workspace.json`、checkpoint DB 与 Trace。
- 优雅重启会在下次启动把活跃 TechScout run 重新入队；若已有 checkpoint/workspace，Harness 尝试恢复。
- 该恢复路径不等于无损 exactly-once。保留 `traces-interrupted.jsonl` / aborted Trace 和所有 attempt 证据。

### C. 任务 `failed` 且无报告

- 查看 Web projection 的 `issues[]`、`run_manifest.json`、sealed Trace 和服务端结构化日志。
- 若是 `execution_initialization_failed`，检查设置加载、输出目录权限和依赖组合。
- 不从日志复制 secret；不把失败投影改写成成功结果。

### D. `artifact_corrupt` 或投影不可读

- 立即停止把该 run 当作权威结果。
- 保存文件摘要、mtime、registry 行和相关日志；不要就地“修补”产物后继续宣称原 run 有效。
- 当前没有自动对账器。是否重跑应创建新 run 并保留旧失败证据。

### E. 磁盘满或 SQLite 写失败

- 停止接收新任务，保留现有文件，不运行 `git clean` 或粗粒度删除命令。
- 检查 state/output 所在卷的空间、inode/配额、权限与 SQLite WAL 文件。
- 扩容或转移前先做一致性备份；恢复后用确定性 Fast Demo 验证写路径。

## 4. 已实现：证据采集清单

- 精确 Git commit、启动参数、Python/OS 版本。
- run ID、公开状态/阶段、created/started/finished 时间。
- registry DB 及 WAL/SHM（复制前应停写或使用 SQLite 安全备份方式）。
- run 目录中文件名、大小、SHA-256；不要收集 secret 值。
- sealed Trace 及其 manifest、中断/aborted Trace。
- 归一化 error/issue code、correlation ID 与脱敏日志窗口。

## 5. 本轮计划：Redis/Worker 运维流程

以下操作面尚未实现，未来必须提供受控 CLI/管理 API，不能依赖手改 Redis：

- 查看 ready/leased/retry_wait/dead_lettered 数量与最老任务年龄。
- 按 run ID 查看 owner、fencing token、lease expiry、attempt 和最后心跳。
- drain Worker：停止 claim，允许有效 lease 完成或在超时后安全退出。
- 对 DLQ 条目执行“检查后重放”，生成新 attempt/token 并保留原失败记录。
- 运行 reaper 与 reconciliation，核对 Redis 调度态、持久 run store 和产物 manifest。
- Redis 故障时切换 API readiness、暂停 claim，并在恢复后从持久事实源重建调度态。

计划告警维度（阈值待演练后确定）：

- 最老 ready age、lease expiry 回收速率、重复 lease loss。
- terminalization failure、artifact digest mismatch、DLQ 增长。
- Redis command error/latency、Worker heartbeat gap、磁盘空间与 SQLite/持久库写错误。

## 6. 未实现

- `/health/live`、`/health/ready` 的明确合同与依赖分级。
- Prometheus 指标、告警规则、Dashboard 和 on-call 路由。
- 自动备份/恢复、RPO/RTO 演练与跨机灾备。
- 安全的管理 CLI、DLQ 重放、Worker drain 和 reconciliation job。
