# 错误协议

## 1. 目标

错误协议要让调用方可靠回答四个问题：发生了什么、是否可重试、应等待多久、运维人员如何关联日志。错误信息不得泄露 secret、原始异常、命令输出或不受控的第三方响应。

## 2. 已实现协议

当前 HTTP 错误响应统一为：

```json
{
  "error": {
    "code": "run_not_found",
    "message": "The requested run was not found.",
    "details": {}
  }
}
```

已实现行为：

- Pydantic 请求校验失败返回 `422 validation_error`，`details.fields` 只列字段路径。
- 已知 `WebError` 由状态码、稳定 code、固定 message 和可选 details 组成。
- 未处理异常返回 `500 internal_error`，响应只暴露随机 `correlation_id`；服务端日志记录该 ID，不回显异常文本。
- API 错误响应带 `Cache-Control: no-store`；API 响应还设置 `nosniff`、CSP 与 frame deny。
- event label 在写库前做 secret 清理、控制字符归一化和长度截断。
- v1 运行详情在任务活跃时返回 `Retry-After: 2`；v2 TechScout 详情尚未统一该响应头。

当前主要 code 包括 `validation_error`、`run_not_found`、`candidate_not_found`、`evidence_not_found`、`report_unavailable`、`queue_full`、`origin_not_allowed`、`artifact_not_ready`、`artifact_corrupt` 与 `internal_error`。

### 已知不一致

`TechScoutProjectionService.create` 抛出 `executor_unavailable`，但基线 `_MESSAGES` 中没有这个键。该路径可能在构造固定 message 时再次失败并降级为 `internal_error`。在修复并增加合同测试前，不应把 `executor_unavailable` 对外承诺为稳定已实现 code。

## 3. 本轮计划：v2 兼容扩展

保留现有三字段，新增可选字段，避免破坏旧客户端：

```json
{
  "error": {
    "code": "queue_full",
    "message": "The run queue is full.",
    "details": {},
    "retryable": true,
    "retry_after_seconds": 2,
    "request_id": "req_01..."
  }
}
```

协议规则：

- `code` 是机器合同；改文案不改 code，移除/改义 code 需要 API 版本升级。
- `message` 是安全、简短的人类提示，不包含内部类名或第三方正文。
- `details` 只能使用逐 code allowlist；不得放 stack trace、路径、secret、完整 prompt 或命令输出。
- `retryable` 表示同一业务意图是否可安全重试，不等同于“HTTP 请求一定要自动重放”。
- `retry_after_seconds` 只在服务端能给出有界建议时返回，并同步设置标准 `Retry-After` header。
- `request_id` 由入口生成并贯穿 API 日志、准入事件和 Worker 日志；终端失败还应带公开的 `run_id`。

## 4. 建议状态码映射（本轮计划）

| HTTP | code | retryable | 说明 |
|---:|---|---:|---|
| 400 | `invalid_state_transition` | 否 | 操作与任务状态冲突且客户端可修正 |
| 404 | `run_not_found` 等 | 否 | 不泄露更多资源存在性信息 |
| 409 | `run_busy` / `artifact_not_ready` | 是 | 业务状态冲突；可轮询或稍后重试 |
| 422 | `validation_error` | 否 | 请求合同不满足 |
| 429 | `tenant_rate_limited` | 是 | 未来认证/租户能力；当前未实现 |
| 503 | `queue_full` / `executor_unavailable` | 是 | 服务暂不可接单；必须给出安全重试建议 |
| 500 | `internal_error` | 视情况 | 只返回关联 ID，默认客户端不得无限自动重试 |

任务内部失败继续通过 run detail 的 `issues[]` 表达，避免把异步任务失败伪装成创建请求的 HTTP 失败。`issues[].code` 与 HTTP `error.code` 使用同一登记表，但语义域分开管理。

## 5. 未实现

- 集中 error-code registry、OpenAPI 枚举和弃用策略。
- 全链路 request ID、中间件注入与结构化日志字段合同。
- v2 统一 `Retry-After`、`retryable` 和重试预算。
- Redis/Worker 错误（`lease_lost`、`stale_fencing_token`、`dead_lettered`）的生产实现。
- 错误码 SLO、按 code 告警和外部依赖错误归一化面板。
